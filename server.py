import os
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
from route_brain import optimize_route

app = Flask(__name__)
CORS(app)  # sta CORS toe op alle routes


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/optimize-route", methods=["POST", "OPTIONS"])
@cross_origin()
def optimize_route_endpoint():
    # CORS preflight (browser stuurt OPTIONS)
    if request.method == "OPTIONS":
        print("=== OPTIONS /optimize-route ontvangen ===")
        return jsonify({"status": "ok"}), 200

    # Echte POST-call
    data = request.get_json(force=True)

    print("=== INKOMENDE DATA /optimize-route ===")
    print(data)
    print("=== EINDE INKOMENDE DATA ===")

    try:
        result = optimize_route(data)

        print("=== UITGAANDE DATA /optimize-route ===")
        print(result)
        print("=== EINDE UITGAANDE DATA ===")

        return jsonify(result)
    except Exception as e:
        print("=== SERVER ERROR /optimize-route ===")
        print(str(e))
        print("=== EINDE ERROR ===")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # alleen voor lokaal draaien; in Railway gebruiken we gunicorn
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
