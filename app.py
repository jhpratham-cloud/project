from gevent import monkey
monkey.patch_all()
import math
import random
import threading
import os

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# Replace your current SocketIO configuration block with this:
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
    logger=True,          # Enables deep logs if something else acts up
    engineio_logger=True, # Forces detailed engine logs
    allow_upgrades=True,
    ping_timeout=60,
    ping_interval=25
)




players = {}
bullets = []
effects = [] # Tracks visual ability effects for the frontend
lock = threading.Lock()

WORLD_WIDTH = 8000
WORLD_HEIGHT = 5000

PLAYER_RADIUS = 20
PLAYER_HEALTH = 100

BULLET_SPEED = 9
BULLET_DAMAGE = 20
BULLET_RADIUS = 5

TICK_RATE = 0.05

# ============================================================
# SERVER-SIDE BOTS CONFIGURATION
# ============================================================
BOTS = [
    {"id": "bot_1", "name": "BOT ALPHA", "x": 1200, "y": 900, "angle": 0, "health": 100, "maxHealth": 100, "speed": 1.2, "fireTimer": 1.0},
    {"id": "bot_2", "name": "BOT BRAVO", "x": 2800, "y": 1300, "angle": 3.14, "health": 100, "maxHealth": 100, "speed": 1.0, "fireTimer": 2.0},
    {"id": "bot_3", "name": "BOT CHARLIE", "x": 4500, "y": 2200, "angle": 0, "health": 100, "maxHealth": 100, "speed": 1.4, "fireTimer": 1.5},
    {"id": "bot_4", "name": "BOT DELTA", "x": 6500, "y": 3800, "angle": 3.14, "health": 100, "maxHealth": 100, "speed": 1.1, "fireTimer": 2.5}
]

def random_spawn():
    x = random.randint(PLAYER_RADIUS, WORLD_WIDTH - PLAYER_RADIUS)
    y = random.randint(PLAYER_RADIUS, WORLD_HEIGHT - PLAYER_RADIUS)
    return x, y

def game_loop():
    while True:
        with lock:
            global effects
            
            # 1. Update Bullets & Collisions
            for bullet in bullets[:]:
                bullet["x"] += bullet["vx"]
                bullet["y"] += bullet["vy"]

                if (bullet["x"] < 0 or bullet["x"] > WORLD_WIDTH or 
                    bullet["y"] < 0 or bullet["y"] > WORLD_HEIGHT):
                    if bullet in bullets: bullets.remove(bullet)
                    continue

                # Player Collision Check
                hit_something = False
                for player_id, player in players.items():
                    if player_id == bullet["owner"]:
                        continue

                    distance = math.hypot(player["x"] - bullet["x"], player["y"] - bullet["y"])
                    if distance < PLAYER_RADIUS + BULLET_RADIUS:
                        player["health"] -= BULLET_DAMAGE
                        effects.append({"type": "hit", "x": bullet["x"], "y": bullet["y"], "damage": BULLET_DAMAGE, "killer": bullet["owner"]})
                        
                        if bullet in bullets: bullets.remove(bullet)
                        hit_something = True

                        if player["health"] <= 0:
                            player["x"], player["y"] = random_spawn()
                            player["health"] = PLAYER_HEALTH
                            effects.append({"type": "kill", "x": player["x"], "y": player["y"]})
                        break

                if hit_something:
                    continue

                # Bot Collision Check
                for bot in BOTS:
                    if bot["health"] <= 0:
                        continue
                    
                    distance = math.hypot(bot["x"] - bullet["x"], bot["y"] - bullet["y"])
                    if distance < PLAYER_RADIUS + BULLET_RADIUS:
                        bot["health"] -= BULLET_DAMAGE
                        effects.append({"type": "hit", "x": bullet["x"], "y": bullet["y"], "damage": BULLET_DAMAGE, "killer": bullet["owner"]})
                        
                        if bullet in bullets: bullets.remove(bullet)
                        
                        if bot["health"] <= 0:
                            effects.append({"type": "kill", "x": bot["x"], "y": bot["y"]})
                            # Respawn bot after death
                            bot["x"], bot["y"] = random_spawn()
                            bot["health"] = bot["maxHealth"]
                        break

            # 2. Basic Bot AI Behavior Loop
            for bot in BOTS:
                if bot["health"] <= 0: continue
                # Find nearest player to track
                if players:
                    nearest_id = min(players.keys(), key=lambda p: math.hypot(players[p]["x"] - bot["x"], players[p]["y"] - bot["y"]))
                    target = players[nearest_id]
                    dx = target["x"] - bot["x"]
                    dy = target["y"] - bot["y"]
                    dist = math.hypot(dx, dy)
                    
                    if dist > 1:
                        bot["angle"] = math.atan2(dy, dx)
                        if dist > 300: # Move closer
                            bot["x"] += math.cos(bot["angle"]) * bot["speed"] * 5
                            bot["y"] += math.sin(bot["angle"]) * bot["speed"] * 5

            # 3. Compile Package State
            state = {
                "players": {
                    player_id: {
                        "name": player["name"],
                        "x": player["x"],
                        "y": player["y"],
                        "health": player["health"],
                    }
                    for player_id, player in players.items()
                },
                "bullets": [
                    {"x": bullet["x"], "y": bullet["y"], "owner": bullet["owner"]}
                    for bullet in bullets
                ],
                "effects": effects,
                "bots": BOTS # Send actual bot tracking arrays to client
            }
            effects = [] # Clear effects after sending

        socketio.emit("state", state)
        socketio.sleep(TICK_RATE)

@app.get("/")
def home():
    return render_template("index.html")

@socketio.on("join")
def join(username):
    name = str(username or "").strip()[:16] or "Player"
    with lock:
        x, y = random_spawn()
        players[request.sid] = {"name": name, "x": x, "y": y, "health": PLAYER_HEALTH}
    emit("joined", {"id": request.sid})

@socketio.on("move")
def move(data):
    if not isinstance(data, dict): return
    with lock:
        player = players.get(request.sid)
        if not player: return
        try:
            new_x = float(data.get("x", player["x"]))
            new_y = float(data.get("y", player["y"]))
        except (TypeError, ValueError): return

        if not math.isfinite(new_x) or not math.isfinite(new_y): return
        player["x"] = max(PLAYER_RADIUS, min(WORLD_WIDTH - PLAYER_RADIUS, new_x))
        player["y"] = max(PLAYER_RADIUS, min(WORLD_HEIGHT - PLAYER_RADIUS, new_y))

@socketio.on("shoot")
def shoot(target):
    if not isinstance(target, dict): return
    with lock:
        player = players.get(request.sid)
        if not player: return
        try:
            target_x = float(target["x"])
            target_y = float(target["y"])
        except (KeyError, TypeError, ValueError): return

        dx = target_x - player["x"]
        dy = target_y - player["y"]
        distance = math.hypot(dx, dy)
        if distance < 0.001: return

        bullets.append({
            "owner": request.sid,
            "x": player["x"],
            "y": player["y"],
            "vx": (dx / distance) * BULLET_SPEED,
            "vy": (dy / distance) * BULLET_SPEED,
        })

# ============================================================
# NEW: SPECIAL ABILITY EVENT LISTENER
# ============================================================
@socketio.on("ability")
def handle_ability(data):
    if not isinstance(data, dict): return
    ability_name = data.get("ability")
    
    with lock:
        player = players.get(request.sid)
        if not player: return
        
        global effects
        if ability_name == "heal":
            player["health"] = min(PLAYER_HEALTH, player["health"] + 30)
            effects.append({"type": "heal", "x": player["x"], "y": player["y"]})
        elif ability_name == "nova":
            effects.append({"type": "nova", "x": player["x"], "y": player["y"], "radius": 320})
            # Damage nearby bots inside nova radius
            for bot in BOTS:
                if math.hypot(bot["x"] - player["x"], bot["y"] - player["y"]) < 320:
                    bot["health"] = max(0, bot["health"] - 40)
        elif ability_name == "dash":
            effects.append({"type": "dash", "x": player["x"], "y": player["y"]})

@socketio.on("disconnect")
def disconnect():
    with lock:
        players.pop(request.sid, None)
        bullets[:] = [b for b in bullets if b["owner"] != request.sid]

if __name__ == "__main__":
    socketio.start_background_task(game_loop)
    port = int(os.environ.get("PORT", 8000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False)

