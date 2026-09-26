
import json, secrets, time, argparse
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import os, socket
import Vibranium

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
rooms={}
rooms_lock=Lock()
def lan_ip():
    """Return the PC's LAN IPv4 address without sending application traffic."""
    try:
        sock=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip=sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip=socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"

def share_url(handler, room, mode):
    # Always return an HTTP link. If the creator opened localhost, use the
    # machine's LAN address so another device on the same Wi-Fi can open it.
    host=lan_ip()
    port=handler.server.server_port
    return f"http://{host}:{port}/?room={room}&mode={mode}"

DIFFICULTY={"easy":3,"medium":4,"hard":5}

def initial_position():
    return Vibranium.Position(Vibranium.initial,0,(True,True),(True,True),0,0)

def actual_move(uci,white_pov):
    if not isinstance(uci,str) or len(uci) not in (4,5): return None
    try:
        i=Vibranium.parse(uci[:2]); j=Vibranium.parse(uci[2:4])
        if not white_pov:i,j=119-i,119-j
        return Vibranium.Move(i,j,uci[4:].upper())
    except Exception:return None

def move_uci(move,white_pov):
    i,j=move.i,move.j
    if not white_pov:i,j=119-i,119-j
    return Vibranium.render(i)+Vibranium.render(j)+move.prom.lower()

def legal_moves(pos):
    out=[]
    for m in pos.gen_moves():
        if pos.board[m.j] in "k": continue
        nxt=pos.move(m)
        if nxt.king_capture() is None: out.append(m)
    return out

def is_in_check(pos):
    return pos.rotate(nullmove=True).king_capture() is not None

def game_status(pos):
    moves=legal_moves(pos)
    if moves:return "check" if is_in_check(pos) else "playing"
    return "checkmate" if is_in_check(pos) else "stalemate"

def board_for(pos,white_pov):
    board=[]
    for r in range(8):
        row=[]
        for c in range(8):
            idx=Vibranium.parse(chr(97+c)+str(8-r))
            if not white_pov:idx=119-idx
            p=pos.board[idx]
            if p in " .\n":row.append(None)
            else:
                if not white_pov:p=p.swapcase()
                row.append({"t":p.upper(),"c":"w" if p.isupper() else "b"})
        board.append(row)
    return board

def captured_for(pos,white_pov):
    start={"P":8,"N":2,"B":2,"R":2,"Q":1}
    counts={"w":{k:0 for k in start},"b":{k:0 for k in start}}
    for row in board_for(pos,white_pov):
        for p in row:
            if p and p["t"] in start: counts[p["c"]][p["t"]]+=1
    glyph={"P":"♟","N":"♞","B":"♝","R":"♜","Q":"♛"}
    trays={"w":[],"b":[]}
    for color in ("w","b"):
        for t,n in start.items():
            trays["b" if color=="w" else "w"] += [glyph[t]]*max(0,n-counts[color][t])
    return trays

def state_payload(g,viewer_color=None):
    pos=g["history"][-1]
    white_pov=(len(g["history"])-1)%2==0
    return {"board":board_for(pos,white_pov),
            "turn":"white" if white_pov else "black",
            "status":game_status(pos),
            "move_history":g["moves"],
            "last_move":g["moves"][-1] if g["moves"] else None,
            "version":g["version"],"white_name":g.get("white_name","White"),
            "black_name":g.get("black_name","Black"),"mode":g.get("mode","computer"),
            "difficulty":g.get("difficulty","medium"),"your_color":viewer_color,
            "captured":captured_for(pos,white_pov),"updated_at":g["updated_at"],
            "opponent_left":g.get("opponent_left",False),"left_name":g.get("left_name"),"left_color":g.get("left_color") }

def apply_uci(g,uci):
    pos=g["history"][-1]; white_pov=(len(g["history"])-1)%2==0
    move=actual_move(uci,white_pov)
    if move is None:return False,"Invalid move"
    key=move_uci(move,white_pov)
    chosen=next((m for m in legal_moves(pos) if move_uci(m,white_pov)==key),None)
    if chosen is None:return False,"Illegal move"
    g["history"].append(pos.move(chosen));g["moves"].append(key);g["version"]+=1;g["updated_at"]=time.time()
    return True,key

def ai_move(g):
    if game_status(g["history"][-1]) in ("checkmate","stalemate"):return None
    depth=DIFFICULTY.get(g.get("difficulty","medium"),4)
    searcher=Vibranium.Searcher();best=None
    for depth_done,gamma,score,move in searcher.search(g["history"]):
        if move is not None:best=move
        if depth_done>=depth:break
    if best is None:
        lm=legal_moves(g["history"][-1])
        if not lm:return None
        best=lm[0]
    white_pov=(len(g["history"])-1)%2==0
    uci=move_uci(best,white_pov)
    ok,_=apply_uci(g,uci)
    return uci if ok else None

def new_game(mode="computer",white_name="Ritik Sen",black_name="JARVIS",difficulty="medium"):
    return {"history":[initial_position()],"moves":[],"version":0,"updated_at":time.time(),
            "mode":mode,"white_name":white_name,"black_name":black_name,"difficulty":difficulty}

def code():
    chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        x="".join(secrets.choice(chars) for _ in range(6))
        if x not in rooms:return x

def find_room(room,token):
    r=rooms.get(room)
    if not r:return None,None
    for c,p in r["players"].items():
        if p and p["token"]==token:return r,c
    return None,None

def json_bytes(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,obj,status=200):
        b=json_bytes(obj);self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("Content-Length","0"));return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        u=urlparse(self.path);path=u.path
        if path=="/":
            data=open(os.path.join(BASE_DIR,"templates","index.html"),"rb").read()
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data);return
        if path.startswith("/api/local/state/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            return self.send_json({"ok":True,"state":state_payload(item["game"])})
        if path.startswith("/api/local2/state/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local2:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            return self.send_json({"ok":True,"state":state_payload(item["game"],"white")})
        if path.startswith("/api/room/") and path.endswith("/state"):
            room=path.split("/")[3].upper();tok=parse_qs(u.query).get("token",[""])[0]
            with rooms_lock:
                r,c=find_room(room,tok)
                if r:
                    r["players"][c]["last_seen"]=time.time()
            if not r:return self.send_json({"ok":False,"error":"Room not found or token invalid"},404)
            return self.send_json({"ok":True,"state":state_payload(r["game"],c)})
        self.send_response(404);self.end_headers()
    def do_POST(self):
        path=urlparse(self.path).path
        try:data=self.body()
        except:return self.send_json({"ok":False,"error":"Invalid JSON"},400)
        if path=="/api/local/new":
            name=str(data.get("name","Player")).strip()[:24] or "Player";color=data.get("color","white");difficulty=data.get("difficulty","medium")
            g=new_game("computer",name if color=="white" else "JARVIS","JARVIS" if color=="white" else name,difficulty)
            if color=="black":ai_move(g)
            tok=secrets.token_urlsafe(12)
            with rooms_lock:rooms["local:"+tok]={"game":g,"token":tok}
            return self.send_json({"ok":True,"token":tok,"state":state_payload(g,color)})
        if path.startswith("/api/local/move/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            g=item["game"];player_color="white" if g["white_name"]!="JARVIS" else "black";turn="white" if (len(g["history"])-1)%2==0 else "black"
            if turn!=player_color:return self.send_json({"ok":False,"error":"Wait for JARVIS"},409)
            ok,msg=apply_uci(g,data.get("move"))
            if not ok:return self.send_json({"ok":False,"error":msg},400)
            ai=None
            if game_status(g["history"][-1]) not in ("checkmate","stalemate"):ai=ai_move(g)
            return self.send_json({"ok":True,"ai_move":ai,"state":state_payload(g,player_color)})
        if path.startswith("/api/local/undo/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            g=item["game"];steps=2 if len(g["history"])>=3 else 1
            if len(g["history"])>1:g["history"]=g["history"][:-steps];g["moves"]=g["moves"][:-steps];g["version"]+=1;g["updated_at"]=time.time()
            return self.send_json({"ok":True,"state":state_payload(g)})
        if path=="/api/local2/new":
            white_name=str(data.get("white_name","Player 1")).strip()[:24] or "Player 1"
            black_name=str(data.get("black_name","Player 2")).strip()[:24] or "Player 2"
            g=new_game("local",white_name,black_name)
            tok=secrets.token_urlsafe(12)
            with rooms_lock:rooms["local2:"+tok]={"game":g,"token":tok}
            return self.send_json({"ok":True,"token":tok,"state":state_payload(g,"white")})
        if path.startswith("/api/local2/move/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local2:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            ok,msg=apply_uci(item["game"],data.get("move"))
            if not ok:return self.send_json({"ok":False,"error":msg},400)
            return self.send_json({"ok":True,"state":state_payload(item["game"],"white")})
        if path.startswith("/api/local2/undo/"):
            tok=path.rsplit("/",1)[-1]
            with rooms_lock:item=rooms.get("local2:"+tok)
            if not item:return self.send_json({"ok":False,"error":"Game expired"},404)
            g=item["game"]
            if len(g["history"])>1:g["history"]=g["history"][:-1];g["moves"]=g["moves"][:-1];g["version"]+=1;g["updated_at"]=time.time()
            return self.send_json({"ok":True,"state":state_payload(g,"white")})
        if path=="/api/room/create":
            name=str(data.get("name","Player")).strip()[:24] or "Player"
            with rooms_lock:
                c=code();room_mode=str(data.get("mode","online"));g=new_game(room_mode,name,"Waiting for opponent")
                tok=secrets.token_urlsafe(12);rooms[c]={"game":g,"players":{"white":{"token":tok,"name":name,"last_seen":time.time()},"black":None},"created_at":time.time()}
            return self.send_json({"ok":True,"room":c,"token":tok,"color":"white","state":state_payload(g,"white"),"share_url":share_url(self,c,room_mode)})
        if path=="/api/room/join":
            c=str(data.get("room","")).strip().upper();name=str(data.get("name","Player 2")).strip()[:24] or "Player 2"
            with rooms_lock:
                r=rooms.get(c)
                if not r:return self.send_json({"ok":False,"error":"Room not found"},404)
                if r["players"]["black"] is not None:return self.send_json({"ok":False,"error":"Room is full"},409)
                tok=secrets.token_urlsafe(12);r["players"]["black"]={"token":tok,"name":name,"last_seen":time.time()};r["game"]["black_name"]=name;r["game"]["version"]+=1;r["game"]["updated_at"]=time.time()
            return self.send_json({"ok":True,"room":c,"token":tok,"color":"black","state":state_payload(r["game"],"black"),"share_url":share_url(self,c,r["game"].get("mode","online"))})
        if path.startswith("/api/room/") and path.endswith("/leave"):
            c=path.split("/")[3].upper();tok=data.get("token","")
            with rooms_lock:
                r,color=find_room(c,tok)
                if not r:return self.send_json({"ok":False,"error":"Room not found"},404)
                player=r["players"].get(color)
                if player:
                    r["game"]["opponent_left"]=True
                    r["game"]["left_name"]=player.get("name",color.title())
                    r["game"]["left_color"]=color
                    r["game"]["version"]+=1;r["game"]["updated_at"]=time.time()
                # Remove the leaver so the remaining player cannot accidentally use the same token.
                r["players"][color]=None
            return self.send_json({"ok":True})
        if path.startswith("/api/room/") and path.endswith("/move"):
            c=path.split("/")[3].upper();tok=data.get("token","")
            with rooms_lock:r,color=find_room(c,tok)
            if not r:return self.send_json({"ok":False,"error":"Room not found"},404)
            g=r["game"];turn="white" if (len(g["history"])-1)%2==0 else "black"
            if color!=turn:return self.send_json({"ok":False,"error":"It is not your turn"},409)
            ok,msg=apply_uci(g,data.get("move"))
            if not ok:return self.send_json({"ok":False,"error":msg},400)
            return self.send_json({"ok":True,"state":state_payload(g,color)})
        if path.startswith("/api/room/") and path.endswith("/undo"):
            c=path.split("/")[3].upper();tok=data.get("token","")
            with rooms_lock:r,color=find_room(c,tok)
            if not r:return self.send_json({"ok":False,"error":"Room not found"},404)
            g=r["game"]
            if len(g["history"])>1:
                g["history"]=g["history"][:-1];g["moves"]=g["moves"][:-1];g["version"]+=1;g["updated_at"]=time.time()
            return self.send_json({"ok":True,"state":state_payload(g,color)})
        if path.startswith("/api/room/") and path.endswith("/new"):
            c=path.split("/")[3].upper();tok=data.get("token","")
            with rooms_lock:r,color=find_room(c,tok)
            if not r:return self.send_json({"ok":False,"error":"Room not found"},404)
            w=r["players"]["white"]["name"];b=r["players"]["black"]["name"] if r["players"]["black"] else "Waiting for opponent"
            r["game"]=new_game(r["game"].get("mode","online"),w,b)
            return self.send_json({"ok":True,"state":state_payload(r["game"],color)})
        self.send_response(404);self.end_headers()

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--host",default="0.0.0.0");ap.add_argument("--port",type=int,default=5000)
    a=ap.parse_args()
    server=ThreadingHTTPServer((a.host,a.port),Handler)
    ip=lan_ip()
    print(f"VIBRANIUM CHESS → http://127.0.0.1:{a.port}")
    print(f"PHONE / SAME WI-FI → http://{ip}:{a.port}")
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=="__main__":main()
