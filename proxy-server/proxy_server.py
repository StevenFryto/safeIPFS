from flask import Flask, request, jsonify
from flask_cors import CORS
from umbral import VerifiedKeyFrag, reencrypt, Capsule
import pymysql
import requests
import json


app = Flask(__name__)
CORS(app)

connection = pymysql.connect(
    host="localhost",
    user="root",
    password="Doncic77++",
    db="safeipfs",
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)


@app.route("/validate_login", methods=["POST"])
def validate_login():
    data = request.json
    username = data.get("username")
    password_hash = data.get("password_hash")
    address = data.get("address")

    try:
        with connection.cursor() as cursor:
            # 查询用户记录
            sql = "SELECT * FROM users WHERE user_id=%s AND password_hash=%s"
            cursor.execute(sql, (username, password_hash))
            user = cursor.fetchone()

            if user:
                # 更新用户在线状态和IP地址
                sql_update = (
                    "UPDATE users SET user_address=%s, is_online=True WHERE user_id=%s"
                )
                cursor.execute(sql_update, (address, username))
                connection.commit()
                return "OK", 200
            else:
                return "Unauthorized", 401
    finally:
        pass


@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password_hash = data.get("password_hash")
    address = data.get("address")

    try:
        with connection.cursor() as cursor:
            # 检查用户是否已存在
            sql = "SELECT * FROM users WHERE user_id=%s"
            cursor.execute(sql, (username,))
            existing_user = cursor.fetchone()

            if existing_user:
                return "User already exists", 400
            else:
                # 创建新用户记录
                sql = "INSERT INTO users (user_id, password_hash, user_address, is_online) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (username, password_hash, address, True))
                connection.commit()
                return "Registration successful", 200
    finally:
        pass


@app.route("/receive", methods=["POST"])  # 创建组，并存储组信息
def receive_data():
    data = request.json
    print("user_id", data["user_id"])
    try:
        with connection.cursor() as cursor:
            sql = """
            INSERT INTO user_groups (group_name, group_description, owner_id, encrypted_file_key, owner_public_key, capsule) 
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                sql,
                (
                    data["group_name"],
                    data["group_description"],
                    data["user_id"],
                    data["encrypted_file_key"],
                    data["owner_public_key"],
                    data["capsule"],
                ),
            )
            connection.commit()
            group_id = cursor.lastrowid
            return jsonify(group_id)
    finally:
        pass


@app.route("/logout", methods=["POST"])
def logout():
    data = request.json
    user_id = data["user_id"]

    try:
        with connection.cursor() as cursor:
            # 更新用户状态
            sql = (
                "UPDATE users SET is_online = %s, user_address = %s WHERE user_id = %s"
            )
            cursor.execute(sql, (False, None, user_id))
            connection.commit()
        return jsonify({"message": "Logout successful"}), 200
    finally:
        pass


@app.route("/get_address", methods=["POST"])
def get_address():
    data = request.json
    group_id = data["group_id"]
    requester_id = data["requester_id"]
    requester_public_key = data["requester_public_key"]

    try:
        with connection.cursor() as cursor:
            # 查询 group owner
            sql = """
                SELECT owner_id, encrypted_file_key, owner_public_key, capsule
                FROM user_groups
                WHERE group_id = %s
            """
            cursor.execute(sql, (group_id,))
            group_info = cursor.fetchone()

            if group_info:
                owner_id = group_info["owner_id"]
                sql = """
                    INSERT INTO request_cache (owner_id, requester_id, requester_public_key, group_id)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(
                    sql, (owner_id, requester_id, requester_public_key, group_id)
                )
                connection.commit()
                print("Request cached.")
                return jsonify({"message": "Request cached."}), 200
            else:
                return jsonify({"message": "Group not found."}), 404
    except:
        return jsonify({"message": "Error processing request."}), 500


@app.route("/get_requests", methods=["POST"])
def get_requests():
    user_id = request.json.get("user_id")
    try:
        with connection.cursor() as cursor:
            sql = "SELECT requester_id, group_id FROM request_cache WHERE owner_id = %s"
            cursor.execute(sql, (user_id,))
            results = cursor.fetchall()
            return jsonify({"requests": results})
    finally:
        pass


@app.route("/get_public_key", methods=["POST"])
def get_public_key():
    owner_id = request.json.get("owner_id")
    requester_id = request.json.get("requester_id")
    group_id = request.json.get("group_id")
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT requester_public_key
            FROM request_cache
            WHERE owner_id = %s AND requester_id = %s AND group_id = %s
            """
            cursor.execute(sql, (owner_id, requester_id, group_id))
            result = cursor.fetchone()
            sql = """
            DELETE FROM request_cache
            WHERE owner_id = %s AND requester_id = %s AND group_id = %s
            """
            cursor.execute(sql, (owner_id, requester_id, group_id))
            connection.commit()
            if result:
                return jsonify({"requester_public_key": result["requester_public_key"]})
            else:
                return jsonify({"error": "No matching record found"}), 404
    finally:
        pass


@app.route("/calculate_cfrag", methods=["POST"])
def calculate_cfrag():
    data = request.json
    kfrag_bytes = data["kfrag"]
    requester_id = data["requester_id"]
    group_id = data["group_id"]
    owner_id = data["owner_id"]
    kfrag = VerifiedKeyFrag.from_verified_bytes(bytes.fromhex(kfrag_bytes))
    with connection.cursor() as cursor:
        sql = """
            SELECT capsule
            FROM user_groups
            WHERE group_id = %s
        """
        cursor.execute(sql, (group_id,))
        try:
            capsule_bytes = cursor.fetchone()["capsule"]
            capsule = Capsule.from_bytes(bytes.fromhex(capsule_bytes))
            cfrag = reencrypt(capsule=capsule, kfrag=kfrag)
            print("cfrag", cfrag)
            sql = """
                INSERT INTO request_complete_cache (owner_id, requester_id, group_id, cfrag) 
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(
                sql,
                (owner_id, requester_id, group_id, bytes(cfrag).hex()),
            )
            connection.commit()
            return jsonify({"message": "Cfrag calculated and stored"}), 200
        except:
            return jsonify({"error": "Error calculating cfrag"}), 500

@app.route('/get_approved_requests', methods=['POST'])
def get_approved_requests():
    requester_id = request.json.get('requester_id')
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT owner_id, group_id
            FROM request_complete_cache
            WHERE requester_id = %s
            """
            cursor.execute(sql, (requester_id,))
            results = cursor.fetchall()
            return jsonify({'requests': results})
    finally:
        pass

@app.route('/process_approved_request', methods=['POST'])
def process_approved_request():
    data = request.json
    requester_id = data['requester_id']
    owner_id = data['owner_id']
    group_id = data['group_id']
    try:
        with connection.cursor() as cursor:
            sql = """
            SELECT cfrag
            FROM request_complete_cache
            WHERE requester_id = %s AND owner_id = %s AND group_id = %s
            """
            cursor.execute(sql, (requester_id, owner_id, group_id))
            cfrag = cursor.fetchone()['cfrag']
            sql = """
            DELETE FROM request_complete_cache
            WHERE owner_id = %s AND requester_id = %s AND group_id = %s
            """
            cursor.execute(sql, (owner_id, requester_id, group_id))
            connection.commit()
            sql = """
                SELECT encrypted_file_key, owner_public_key, capsule
                FROM user_groups
                WHERE group_id = %s
            """
            cursor.execute(sql, (group_id,))
            group_info = cursor.fetchone()
            return jsonify({
                'cfrag': cfrag,
                'encrypted_file_key': group_info['encrypted_file_key'],
                'owner_public_key': group_info['owner_public_key'],
                'capsule': group_info['capsule']
            })
    finally:
        pass

@app.route('/test', methods=['GET'])
def test():
    print("test")


if __name__ == "__main__":
    app.run(port=5001, debug=True, host='0.0.0.0')