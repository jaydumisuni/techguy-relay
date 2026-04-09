from flask import Flask, request, jsonify
from flask_socketio import SocketIO, join_room, emit
import random
import string

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

sessions = {}  # code -> {tech_sid, client_sid}

def generate_code():
    return "TG-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


@app.route("/register", methods=["POST"])
def register():
    code = generate_code()
    sessions[code] = {"tech_sid": None, "client_sid": None}
    return jsonify({"code": code})


@app.route("/resolve/<code>", methods=["GET"])
def resolve(code):
    if code in sessions:
        return jsonify({"status": "ok"})
    return jsonify({"status": "not_found"}), 404


@socketio.on("join")
def on_join(data):
    code = data.get("code")
    role = data.get("role")

    if code not in sessions:
        emit("error", {"msg": "Invalid code"})
        return

    join_room(code)

    if role == "tech":
        sessions[code]["tech_sid"] = request.sid
        print(f"[TECH CONNECTED] {code}")

    elif role == "client":
        sessions[code]["client_sid"] = request.sid
        print(f"[CLIENT CONNECTED] {code}")

    emit("ready", room=code)


@socketio.on("relay")
def relay(data):
    code = data.get("code")
    payload = data.get("payload")

    if code not in sessions:
        return

    emit("relay", {"payload": payload}, room=code, include_self=False)


@socketio.on("disconnect")
def disconnect():
    print("Client disconnected")


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
