"""C 시험 서버(pc/)의 anchor_observation 수신 코드 발췌 — 팀장 서버 수신 확장 참고용.

원본: pc/squadlink/schema.py(_anchor_observation), pc/squadlink/hub.py(Hub._ingest 일부, Hub._anchor, Hub.snapshot 일부).
Python이지만 규칙은 그대로 옮기면 된다. 공통 머리·transport 검사와 중복 제거 키(source+node_id+boot_id+seq)는
다른 패킷과 같은 경로를 탄다.

핵심 규칙
1. 검사(규격 9장): anchor_id·observed_node_id·observed_boot_id는 빈 문자열이 아닌 문자열, observed_seq·observation_age_ms는
   0 이상 정수, rssi_dbm은 유한한 숫자. anchor_id가 머리의 node_id와 다르면 경고.
2. 앵커 관측은 노드의 표시 상태(연결·최신값·출처 선택)를 바꾸지 않는다. 환경 노드가 vtemp로 환경 패킷만 simulation을
   보내는 동안에도 실제 관측(device)은 받는다. 순서·중복은 앵커 노드의 seq로 거른다.
3. 보관 키는 (anchor_id, observed_node_id, source). 실제·가상 관측을 섞지 않는다(앵커 시험 모드의 가상 관측 포함).
4. 관측 시각 = 서버 수신 시각 − observation_age_ms. 같은 키에 더 최근 관측이 이미 있으면 버린다(늦게 온 보고).
5. 화면·API에는 age_ms(지금 − 관측 시각)를 매번 계산해 낸다. 오래된 관측(예: 45초)은 구역 미확보로 본다.
"""

# ----- pc/squadlink/schema.py -----
def _anchor_observation(c, p, pkt):
    path = "payload"
    c.string(p, "anchor_id", path)
    c.string(p, "observed_node_id", path)
    c.string(p, "observed_boot_id", path)
    c.integer(p, "observed_seq", path, minimum=0)
    if c.required(p, "rssi_dbm", path) and not is_num(p["rssi_dbm"]):
        c.err(f"{path}.rssi_dbm", "숫자여야 함")
    c.integer(p, "observation_age_ms", path, minimum=0)
    if not c.errors and p["anchor_id"] != pkt["node_id"]:
        c.warn(f"{path}.anchor_id", "원본 node_id와 같아야 함")


# ----- pc/squadlink/hub.py: Hub._ingest 안, 출처 선택보다 앞 -----
# # 앵커 관측은 노드의 표시 상태를 바꾸지 않으므로 출처 선택과 무관하게 받는다.
# # (환경 노드가 vtemp 시험으로 환경 패킷만 simulation으로 보내도 실제 관측은 device로 온다)
# if ptype == "anchor_observation" and n.active is not None and source != n.active:
#     order = self._sequence(n, stream, pkt, now)
#     if order == "dup":
#         n.c["dup"] += 1
#         self.totals["dup"] += 1
#         return "dup", errors, warnings
#     self.totals["accepted" if order == "new" else order] += 1
#     n.kinds.add(ptype)
#     self._anchor(pkt, input_, now, wall)
#     return ("ok" if order == "new" else order), errors, warnings


# ----- pc/squadlink/hub.py: Hub._anchor -----
def _anchor(self, pkt, input_, now, wall):
    p = pkt["payload"]
    age_s = p["observation_age_ms"] / 1000.0
    key = (pkt["node_id"], p["observed_node_id"], pkt["source"])  # 실제·가상 앵커 관측을 섞지 않는다
    cur = self.anchors.get(key)
    observed = now - age_s
    if cur is not None and cur["_observed"] > observed:
        return  # 더 최근 관측이 이미 있다
    self.anchors[key] = {
        "_observed": observed,
        "anchor_id": pkt["node_id"], "observed_node_id": p["observed_node_id"],
        "observed_boot_id": p["observed_boot_id"], "observed_seq": p["observed_seq"],
        "rssi_dbm": p["rssi_dbm"], "observed_at": iso(wall - age_s), "received_at": iso(wall),
        "source": pkt["source"], "route": pkt["transport"]["route"], "input": input_,
    }

# ----- pc/squadlink/hub.py: Hub.snapshot 안 -----
# anchors = []
# for rec in sorted(self.anchors.values(),
#                  key=lambda r: (r["anchor_id"], r["observed_node_id"], r["source"])):
#     a = {k: v for k, v in rec.items() if not k.startswith("_")}
#     a["age_ms"] = max(0, int((now - rec["_observed"]) * 1000))
#     anchors.append(a)
