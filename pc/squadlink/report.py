"""로그 요약: 실물 시험에서 기록할 수신·누락·송신량을 한 번에 뽑는다.

입력은 서버 로그(logs/<시각>/rx.jsonl 또는 그 폴더)나, 장치 USB 출력을 그대로 저장한 NDJSON 파일이다.
서버 판정(result)은 전체 집계에만 쓰고, 노드별 수치는 패킷의 source·node_id·boot_id·seq로 다시 센다.
원시 NDJSON 줄은 서버와 같은 검사기(schema.validate)를 통과한 것만 센다.

- 노드별(노드마다 한 줄, 출처별 패킷 수 함께): 고유 패킷 수, 중복, 누락, 손실률, 분당 송신.
  seq는 규격상 부팅 내 모든 패킷 공통이라 누락·송신량은 노드·boot 단위로 센다. vtemp 시험처럼 실측·가상이 한 boot의
  번호를 나눠 써도 가짜 누락이 생기지 않는다. 분당 송신은 boot마다 처음·마지막으로 받은 패킷 사이의 seq 증가 /
  장치 uptime 증가다.
- 경로별: 어떤 gateway_id로 몇 개가 들어왔는지. 노드가 USB로 자기 송신분을 함께 내면(환경 노드)
  그것을 보낸 목록으로 보고 다른 게이트웨이의 BLE 수신률을 계산한다.
- 환경 노드 송신량: "stats" 진단 줄 사이의 차이(같은 boot). 구간 양 끝의 tx_mode·anchor_enabled가 같아야
  그 모드의 값으로 본다(다르면 "전환 포함").
- 앵커 관측: 앵커·병사 쌍마다 RSSI 평균·표준편차·최소·최대, 관측 경과 중앙값
- 사건: 출처·종류별 사건 수와 보고 수
- 시험 조건: 부팅 진단 줄의 펌웨어 판(fw)·송신 모드·앵커·앵커 시험 모드·가상 센서 모드
- 오류: boot마다 마지막 stats의 누적 오류(버림·광고 실패·앵커 표 가득·큐밀림·스캔 재시작)와 서버 판정 무효·처리 오류 줄 수
"""

import json
import os
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .ingest import classify_line
from .schema import validate

KST = timezone(timedelta(hours=9))
TX_KEYS = ("packets", "windows", "est_adv_events", "payload_bytes", "dropped", "adv_fail")
ANCHOR_KEYS = ("rx_total", "rx_soldier", "rx_relayed_skip", "rx_simulation_skip", "rx_simulation",
               "table_full_skip", "reports", "queue_full_skip", "scan_restarts")
# 부팅 진단 줄에서 시험 조건으로 남길 값
BOOT_KEYS = ("node_id", "boot_id", "fw", "tx_mode", "anchor", "anchor_test", "vsensor")
# stats의 누적 오류 카운터
ERROR_KEYS = (("tx", "dropped"), ("tx", "adv_fail"), ("anchor", "table_full_skip"), ("anchor", "queue_full_skip"),
              ("anchor", "scan_restarts"))

# 서버가 검사를 통과시킨 줄의 판정. 이 줄들의 obj만 노드별로 센다.
ACCEPTED_RESULTS = ("ok", "late", "stale_boot", "dup", "shadowed")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def read_log(path):
    """(rx_ts 또는 None, result, 객체) 목록. result: 서버 판정, "diag", "text", 또는 None(원시 NDJSON)."""
    if os.path.isdir(path):
        path = os.path.join(path, "rx.jsonl")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            kind, obj = classify_line(line)
            if kind == "diag":
                out.append((None, "diag", obj))
            elif kind != "data":
                out.append((None, "text", None))
            elif "rx_ts" in obj and "result" in obj:  # 서버 로그 한 줄
                ts = obj["rx_ts"] if isinstance(obj["rx_ts"], (int, float)) else None
                res = obj["result"]
                body = obj.get("diag") if res == "diag" else obj.get("obj")
                out.append((ts, res, body))
            else:  # 원시 NDJSON: 서버와 같은 검사를 거친다
                pkt, errors, _ = validate(obj)
                out.append((None, None, pkt) if not errors else (None, "invalid", obj))
    return out


class _NodeAcc:
    def __init__(self):
        self.copies = 0
        self.seen = defaultdict(set)        # boot -> {seq}
        self.uptime = {}                    # boot -> [min, max]
        self.types = Counter()
        self.paths = defaultdict(lambda: defaultdict(set))  # gateway_id -> boot -> {seq}
        self.routes = Counter()


def _span(values):
    return (min(values), max(values)) if values else (None, None)


def _iso_kst(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d %H:%M:%S") if ts is not None else None


def summarize(records):
    results = Counter()
    times = []
    nodes = defaultdict(_NodeAcc)
    anchors = defaultdict(lambda: {"rssi": [], "age": []})
    events = defaultdict(lambda: {"ids": set(), "reports": 0})
    stats_lines = defaultdict(list)  # (node_id, boot_id) -> [stats diag]
    boots = []                       # 부팅 진단 줄

    for ts, result, obj in records:
        results[result if result is not None else "raw"] += 1
        if ts is not None:
            times.append(ts)
        if result == "diag":
            if isinstance(obj, dict) and obj.get("type") == "stats":
                stats_lines[(obj.get("node_id"), obj.get("boot_id"))].append(obj)
            elif isinstance(obj, dict) and obj.get("type") == "boot":
                boots.append({k: obj.get(k) for k in BOOT_KEYS})
            continue
        if (result is not None and result not in ACCEPTED_RESULTS) or not isinstance(obj, dict):
            continue
        key = (obj["node_id"], obj["source"])
        n = nodes[key]
        boot, seq, t = obj["boot_id"], obj["seq"], obj["transport"]
        n.copies += 1
        gw = t.get("gateway_id") if isinstance(t.get("gateway_id"), str) else "?"
        n.paths[gw][boot].add(seq)
        n.routes[(gw, t.get("route"))] += 1
        if seq in n.seen[boot]:
            continue  # 같은 패킷의 다른 사본(반복 광고·다른 경로)
        n.seen[boot].add(seq)
        span = n.uptime.setdefault(boot, [obj["uptime_ms"], obj["uptime_ms"]])
        span[0], span[1] = min(span[0], obj["uptime_ms"]), max(span[1], obj["uptime_ms"])
        ptype, p = obj["packet_type"], obj["payload"]
        n.types[ptype] += 1
        if ptype == "anchor_observation":
            a = anchors[(p.get("anchor_id"), p.get("observed_node_id"), obj["source"])]
            if isinstance(p.get("rssi_dbm"), (int, float)):
                a["rssi"].append(p["rssi_dbm"])
            if _is_int(p.get("observation_age_ms")):
                a["age"].append(p["observation_age_ms"])
        elif ptype == "event" and isinstance(p.get("event_id"), str):
            e = events[(obj["source"], p.get("event_type"))]
            e["ids"].add(p["event_id"])
            e["reports"] += 1

    t0, t1 = _span(times)
    return {
        "period": {"start": _iso_kst(t0), "end": _iso_kst(t1),
                   "seconds": round(t1 - t0, 1) if t0 is not None else None},
        "results": dict(results),
        "nodes": _node_rows(nodes),
        "paths": _path_rows(nodes),
        "tx_intervals": _tx_intervals(stats_lines),
        "conditions": boots,
        "errors": _errors(stats_lines, results),
        "anchors": [_anchor_row(k, a) for k, a in sorted(anchors.items(), key=lambda kv: tuple(map(str, kv[0])))],
        "events": [{"source": s, "event_type": et, "events": len(e["ids"]), "reports": e["reports"]}
                   for (s, et), e in sorted(events.items(), key=lambda kv: tuple(map(str, kv[0])))],
    }


def _node_rows(nodes):
    """노드마다 한 줄. 출처별로 모은 것을 노드·boot 단위로 합친다(seq는 부팅 내 모든 패킷 공통)."""
    by_node = defaultdict(list)
    for (node_id, source), n in nodes.items():
        by_node[node_id].append((source, n))
    rows = []
    for node_id, parts in sorted(by_node.items()):
        seen, uptime = defaultdict(set), {}
        types, routes, sources = Counter(), Counter(), {}
        copies = 0
        for source, n in sorted(parts, key=lambda p: str(p[0])):
            sources[source] = sum(len(s) for s in n.seen.values())
            copies += n.copies
            types.update(n.types)
            routes.update(n.routes)
            for boot, s in n.seen.items():
                seen[boot] |= s
            for boot, (lo, hi) in n.uptime.items():
                cur = uptime.setdefault(boot, [lo, hi])
                cur[0], cur[1] = min(cur[0], lo), max(cur[1], hi)
        packets = sum(len(s) for s in seen.values())
        missing = sum(max(s) - min(s) + 1 - len(s) for s in seen.values())
        # 같은 boot 안에서 seq와 uptime은 함께 늘어나므로, 처음·마지막 패킷 사이 seq 증가가 그동안 보낸 패킷 수다
        sent_between = sum(max(s) - min(s) for s in seen.values())
        span_ms = sum(hi - lo for lo, hi in uptime.values())
        rows.append({
            "node_id": node_id, "sources": sources, "packets": packets, "copies": copies,
            "dup": copies - packets, "missing": missing,
            "loss_pct": round(100.0 * missing / (packets + missing), 2) if packets else None,
            "boots": len(seen), "per_min": round(sent_between * 60000.0 / span_ms, 2) if span_ms > 0 else None,
            "types": dict(sorted(types.items())),
            "routes": {f"{gw}/{route}": c for (gw, route), c in sorted(routes.items(), key=lambda kv: str(kv[0]))},
        })
    return rows


def _path_rows(nodes):
    """게이트웨이별 수신 수. 노드 자신이 USB로 낸 사본(gateway_id == node_id)이 있으면 그것을 보낸 목록으로 본다."""
    rows = []
    for (node_id, source), n in sorted(nodes.items()):
        sent = n.paths.get(node_id)
        for gw, boots in sorted(n.paths.items()):
            got = sum(len(s) for s in boots.values())
            row = {"node_id": node_id, "source": source, "gateway_id": gw, "packets": got,
                   "sent": None, "received_pct": None}
            if sent is not None and gw != node_id:
                # 이 게이트웨이가 켜져 있던 범위(boot마다 받은 seq 범위)의 송신분만 분모로 쓴다
                total = hit = 0
                for boot, seqs in boots.items():
                    lo, hi = min(seqs), max(seqs)
                    own = {s for s in sent.get(boot, ()) if lo <= s <= hi}
                    total += len(own)
                    hit += len(own & seqs)
                if total:
                    row["sent"], row["packets"] = total, hit
                    row["received_pct"] = round(100.0 * hit / total, 2)
            rows.append(row)
    return rows


def _num(d, k):
    v = d.get(k) if isinstance(d, dict) else None
    return v if _is_int(v) else None


def _label(a, b, key):
    va, vb = a.get(key), b.get(key)
    if va is None and vb is None:
        return None
    return va if va == vb else "전환 포함"


def _tx_intervals(stats_lines):
    rows = []
    for (node_id, boot_id), lines in sorted(stats_lines.items(), key=lambda kv: tuple(map(str, kv[0]))):
        lines = [s for s in lines if _num(s, "uptime_ms") is not None]
        lines.sort(key=lambda s: s["uptime_ms"])
        for a, b in zip(lines, lines[1:]):
            dur = b["uptime_ms"] - a["uptime_ms"]
            if dur <= 0:
                continue
            row = {"node_id": node_id, "boot_id": boot_id, "from_uptime_s": round(a["uptime_ms"] / 1000, 1),
                   "seconds": round(dur / 1000, 1), "fw": _label(a, b, "fw"), "tx_mode": _label(a, b, "tx_mode"),
                   "anchor_enabled": _label(a, b, "anchor_enabled"), "anchor_test": _label(a, b, "anchor_test"),
                   "vsensor": _label(a, b, "vsensor"), "vtemp": _label(a, b, "vtemp")}
            for group, keys in (("tx", TX_KEYS), ("anchor", ANCHOR_KEYS)):
                for k in keys:
                    va, vb = _num(a.get(group), k), _num(b.get(group), k)
                    row[f"{group}_{k}"] = vb - va if va is not None and vb is not None else None
            p = row["tx_packets"]
            row["tx_packets_per_min"] = round(p * 60000.0 / dur, 2) if p is not None else None
            rows.append(row)
    return rows


def _errors(stats_lines, results):
    """boot마다 마지막 stats의 누적 오류 카운터와, 로그 전체의 무효·처리 오류·JSON 아닌 줄 수."""
    rows = []
    for (node_id, boot_id), lines in sorted(stats_lines.items(), key=lambda kv: tuple(map(str, kv[0]))):
        lines = [s for s in lines if _num(s, "uptime_ms") is not None]
        if not lines:
            continue
        last = max(lines, key=lambda s: s["uptime_ms"])
        row = {"node_id": node_id, "boot_id": boot_id, "uptime_s": round(last["uptime_ms"] / 1000, 1)}
        for group, k in ERROR_KEYS:
            row[f"{group}_{k}"] = _num(last.get(group), k)
        rows.append(row)
    return {"by_boot": rows, "invalid_lines": results.get("invalid", 0), "error_lines": results.get("error", 0),
            "text_lines": results.get("text", 0)}


def _anchor_row(key, a):
    anchor_id, observed, source = key
    r = a["rssi"]
    return {"anchor_id": anchor_id, "observed_node_id": observed, "source": source, "reports": len(r),
            "rssi_mean": round(statistics.fmean(r), 1) if r else None,
            "rssi_sd": round(statistics.pstdev(r), 1) if len(r) > 1 else None,
            "rssi_min": min(r) if r else None, "rssi_max": max(r) if r else None,
            "age_median_ms": statistics.median(a["age"]) if a["age"] else None}


# ----- 출력 -----
def _table(headers, rows):
    cells = [[("-" if v is None else str(v)) for v in row] for row in rows]
    widths = [max([_w(h)] + [_w(c[i]) for c in cells]) for i, h in enumerate(headers)]
    out = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)).rstrip()]
    out += ["  ".join(_pad(c[i], widths[i]) for i in range(len(headers))).rstrip() for c in cells]
    return "\n".join(out)


def _w(s):  # 한글 등 넓은 글자는 두 칸
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def _pad(s, width):
    return s + " " * (width - _w(s))


def format_text(rep):
    p, r = rep["period"], rep["results"]
    lines = [f"기간(KST): {p['start'] or '-'} ~ {p['end'] or '-'} ({p['seconds'] if p['seconds'] is not None else '-'}초)",
             "줄 판정: " + (" · ".join(f"{k} {v}" for k, v in sorted(r.items())) or "없음"), ""]
    lines.append("[노드별 수신] 누락 = boot마다 받은 seq 범위 안의 빈 번호(출처 무관), 분당 = 보낸 패킷(seq)/장치 uptime")
    lines.append(_table(
        ["node_id", "출처별 패킷", "패킷", "중복", "누락", "손실%", "boot", "분당", "종류"],
        [[n["node_id"], ", ".join(f"{k} {v}" for k, v in n["sources"].items()), n["packets"], n["dup"],
          n["missing"], n["loss_pct"], n["boots"], n["per_min"],
          ", ".join(f"{k} {v}" for k, v in n["types"].items())] for n in rep["nodes"]]))
    lines += ["", "[경로별 수신] 수신률 = 노드가 USB로 낸 송신분 중 그 게이트웨이가 받은 비율"]
    lines.append(_table(["node_id", "source", "gateway_id", "받음", "송신분", "수신률%"],
                        [[x["node_id"], x["source"], x["gateway_id"], x["packets"], x["sent"], x["received_pct"]]
                         for x in rep["paths"]]))
    if rep["conditions"]:
        lines += ["", "[시험 조건] 부팅 진단 줄"]
        lines.append(_table(["node_id", "boot", "fw", "tx_mode", "앵커", "앵커시험", "가상센서"],
                            [[c["node_id"], c["boot_id"], c["fw"], c["tx_mode"], c["anchor"], c["anchor_test"],
                              c["vsensor"]] for c in rep["conditions"]]))
    if rep["tx_intervals"]:
        lines += ["", "[환경 노드 송신량] stats 진단 줄 사이 차이 (est_adv는 추정치)"]
        lines.append(_table(
            ["node_id", "boot", "시작s", "구간s", "tx_mode", "앵커", "앵커시험", "가상센서", "패킷", "분당", "창",
             "est_adv", "바이트", "버림", "광고실패", "앵커수신", "앵커가상", "앵커보고", "큐밀림", "스캔재시작"],
            [[x["node_id"], x["boot_id"], x["from_uptime_s"], x["seconds"], x["tx_mode"], x["anchor_enabled"],
              x["anchor_test"], x["vsensor"], x["tx_packets"], x["tx_packets_per_min"], x["tx_windows"],
              x["tx_est_adv_events"], x["tx_payload_bytes"], x["tx_dropped"], x["tx_adv_fail"],
              x["anchor_rx_soldier"], x["anchor_rx_simulation"], x["anchor_reports"], x["anchor_queue_full_skip"],
              x["anchor_scan_restarts"]] for x in rep["tx_intervals"]]))
    er = rep["errors"]
    lines += ["", f"[오류] 서버 판정 무효 {er['invalid_lines']} · 처리 오류 {er['error_lines']} · JSON 아닌 줄 {er['text_lines']}"
                  " (아래는 boot마다 마지막 stats의 누적값)"]
    if er["by_boot"]:
        lines.append(_table(["node_id", "boot", "uptime s", "버림", "광고실패", "앵커표가득", "큐밀림", "스캔재시작"],
                            [[x["node_id"], x["boot_id"], x["uptime_s"], x["tx_dropped"], x["tx_adv_fail"],
                              x["anchor_table_full_skip"], x["anchor_queue_full_skip"], x["anchor_scan_restarts"]]
                             for x in er["by_boot"]]))
    if rep["anchors"]:
        lines += ["", "[앵커 관측 RSSI]"]
        lines.append(_table(["anchor_id", "병사 노드", "source", "보고", "평균", "표준편차", "최소", "최대",
                             "경과 중앙값ms"],
                            [[a["anchor_id"], a["observed_node_id"], a["source"], a["reports"], a["rssi_mean"],
                              a["rssi_sd"], a["rssi_min"], a["rssi_max"], a["age_median_ms"]]
                             for a in rep["anchors"]]))
    if rep["events"]:
        lines += ["", "[사건]"]
        lines.append(_table(["source", "event_type", "사건", "보고"],
                            [[e["source"], e["event_type"], e["events"], e["reports"]] for e in rep["events"]]))
    return "\n".join(lines)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="SQUAD LINK 로그 요약(수신·누락·송신량)")
    ap.add_argument("log", help="rx.jsonl, 그 폴더, 또는 장치 출력을 저장한 NDJSON")
    ap.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    args = ap.parse_args(argv)
    try:
        records = read_log(args.log)
    except (OSError, UnicodeDecodeError) as e:
        print(f"로그를 읽을 수 없음: {e}", file=sys.stderr)
        return 1
    rep = summarize(records)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(format_text(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
