"""게임 요청(module + payload)을 LLM 요청으로 바꾼다.

각 모듈의 프롬프트 조립은 여기서만 한다. 게임 쪽 payload 는 신뢰하지 않는 입력으로 보고
타입을 확인하고 길이를 자른 뒤 사용한다. Lua 는 구조화된 사실만 보내고, 문장은 여기서 만든다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 배포판(PyInstaller)에서는 프롬프트가 압축 해제 폴더(sys._MEIPASS)에 있다
PROMPTS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "prompts"
MAX_TEXT = 500
MAX_EPISODES = 30
MAX_MEMOIR_DAYS = 60
NAME_LIMIT = 40


class ModuleError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class LLMRequest:
    module: str
    model: str
    system: str
    messages: list[dict[str, str]]
    max_tokens: int
    effort: str | None = None
    json_schema: dict | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def clip(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value if value is not None else "")[:limit]


def as_list(value: Any) -> list:
    """Lua 의 빈 테이블은 {} 로 오므로 빈 dict 도 빈 리스트로 본다."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and not value:
        return []
    return []


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- debug

def build_debug(payload: dict, mcfg: dict) -> LLMRequest:
    text = clip(payload.get("text")).strip()
    if not text:
        raise ModuleError("empty_text")
    return LLMRequest(
        module="debug",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("debug"),
        messages=[{"role": "user", "content": text}],
        max_tokens=int(mcfg.get("max_tokens", 1024)),
        effort=mcfg.get("effort"),
    )


# ---------------------------------------------------------------- journal

LANGUAGES = {"KO": "Korean", "EN": "English", "JP": "Japanese", "CH": "Simplified Chinese",
             "CN": "Traditional Chinese", "DE": "German", "FR": "French", "ES": "Spanish",
             "RU": "Russian", "PL": "Polish", "PTBR": "Brazilian Portuguese"}

BODY_PARTS = {
    "Hand_L": "left hand", "Hand_R": "right hand", "ForeArm_L": "left forearm", "ForeArm_R": "right forearm",
    "UpperArm_L": "left upper arm", "UpperArm_R": "right upper arm", "Torso_Upper": "chest",
    "Torso_Lower": "stomach", "Head": "head", "Neck": "neck", "Groin": "groin",
    "UpperLeg_L": "left thigh", "UpperLeg_R": "right thigh", "LowerLeg_L": "left shin",
    "LowerLeg_R": "right shin", "Foot_L": "left foot", "Foot_R": "right foot",
}

WOUNDS = {"scratched": "scratched", "bitten": "BITTEN", "cut": "cut (laceration)",
          "deep": "deep wound", "fracture": "fracture"}

MOODLES = {"PANIC": "panic", "BORED": "boredom", "UNHAPPY": "unhappiness", "STRESS": "stress",
           "TIRED": "tiredness", "HUNGRY": "hunger", "THIRST": "thirst", "SICK": "sickness",
           "PAIN": "pain", "INJURED": "injury"}

DAY_TYPES = {
    "combat_day": "a day of heavy fighting or injury",
    "expedition": "a long trip far from home",
    "local_scavenge": "scavenging near home",
    "stayed_home": "stayed at home, nothing much happened",
}


# 게임 Translate/<언어>/MapLabel.json 과 같은 현지어 마을 이름. 게임 Lua 소스에는 비 ASCII 문자열을 둘 수 없어
# (Kahlua 가 소스 파일을 UTF-8 로 읽지 않음) 여기서 붙인다.
TOWN_NAMES = {
    "KO": {
        "Brandenburg": "브랜든버그", "Echo Creek": "에코 크릭", "Ekron": "에크론", "Fallas Lake": "팔라스 레이크",
        "Irvington": "어빙턴", "Louisville": "루이빌", "March Ridge": "마치 리지", "Muldraugh": "멀드로",
        "Riverside": "리버사이드", "Rosewood": "로즈우드", "Valley Station": "밸리 스테이션", "West Point": "웨스트 포인트",
    },
}


def language_name(code: Any) -> str:
    return LANGUAGES.get(str(code or "EN").upper(), "English")


def local_town(town: str, lang: Any) -> str:
    return TOWN_NAMES.get(str(lang or "").upper(), {}).get(town, "")


def with_local(town: str, lang: Any) -> str:
    local = local_town(town, lang)
    return f"{town} [{local}]" if local else town


def format_place(place: dict, lang: Any = None) -> str:
    place = as_dict(place)
    parts = []
    town = clip(place.get("town"), 40)
    town_local = clip(place.get("townLocal"), 40) or local_town(town, lang)
    if town:
        label = f"{town} [{town_local}]" if town_local and town_local != town else town
        dist = as_int(place.get("townDist"), 0)
        parts.append(label if dist < 400 else f"countryside {dist} tiles from {label}")
    else:
        parts.append("Knox County countryside")
    landmark = clip(place.get("landmark"), 60)
    if landmark:
        parts.append(f"near {landmark}")
    rooms = [clip(r, 30) for r in as_list(place.get("rooms"))[:5] if r]
    if place.get("inside"):
        kind = "a house" if place.get("residential") else "a building"
        parts.append(f"inside {kind}" + (f" (rooms: {', '.join(rooms)})" if rooms else ""))
    else:
        parts.append("outdoors")
    via = [with_local(clip(t, 40), lang) for t in as_list(place.get("via"))[:6] if t]
    if via:
        parts.append("traveling through " + ", ".join(via))
    if place.get("home"):
        parts.append("this is their home")
    return ", ".join(parts)


def format_harm(harm: list) -> str:
    out = []
    for h in as_list(harm)[:8]:
        h = as_dict(h)
        who = clip(h.get("who"), 40)
        part = BODY_PARTS.get(str(h.get("part")), clip(h.get("part"), 30))
        kind = WOUNDS.get(str(h.get("kind")), clip(h.get("kind"), 20))
        out.append(f"{who}: {kind} on {part}" if who else f"{kind} on {part}")
    return "; ".join(out)


# 일지용 행동 (게임 Sensor.ACT_KINDS 와 같은 목록). 없는 종류는 버린다.
ACT_TEXT = {
    "craft": "crafted",
    "dismantle": "took apart for parts",
    "cook": "cooked",
    "build": "built",
    "forage": "foraged",
    "fish": "caught fish",
    "fish_net": "checked fishing nets",
    "chop": "chopped at trees",
    "plant": "planted",
    "harvest": "harvested crops",
    "plow": "dug furrows in a field",
    "water_plants": "watered the crops",
    "trap": "set traps",
    "butcher": "butchered animals",
    "animals": "tended animals (milking, shearing, eggs, feeding)",
    "read": "read",
    "treat_other": "treated the wounds of",
    "sew": "patched clothes",
    "barricade": "barricaded windows or doors",
    "bury": "buried the dead",
    "burn_corpse": "burned corpses",
    "mechanic": "worked on a vehicle",
    "write": "wrote something down",
    "exercise": "exercised",
}
MAX_ACT_NAMES = 6
# 대상 이름이 없을 때 쓰는 문구
ACT_ALONE = {"treat_other": "treated another survivor's wounds", "read": "read a book"}


def format_acts(acts: Any) -> str:
    out = []
    for kind, a in as_dict(acts).items():
        verb = ACT_TEXT.get(str(kind))
        a = as_dict(a)
        total = as_int(a.get("n"))
        if not verb or total <= 0:
            continue
        names = sorted(((clip(w, 40), as_int(n)) for w, n in as_dict(a.get("w")).items() if w),
                       key=lambda x: -x[1])[:MAX_ACT_NAMES]
        detail = ", ".join(f"{w} x{n}" if n > 1 else w for w, n in names)
        if detail:
            out.append(f"{verb}: {detail}")
        else:
            verb = ACT_ALONE.get(str(kind), verb)
            out.append(f"{verb} ({total} times)" if total > 1 else verb)
    return "; ".join(out)


def format_episode(ep: dict, lang: Any = None) -> str:
    ep = as_dict(ep)
    fields = [f"{clip(ep.get('from'), 5)}-{clip(ep.get('to'), 5)}", format_place(ep.get("place"), lang)]
    companions = [clip(n, 40) for n in as_list(ep.get("with"))[:6] if n]
    if companions:
        fields.append("with " + ", ".join(companions))
    kills = as_int(ep.get("kills"))
    if kills:
        fields.append(f"killed {kills} zombies")
    zombies = as_int(ep.get("zombiesNear"))
    if zombies >= 5:
        fields.append(f"about {zombies} zombies nearby at peak")
    harm = format_harm(ep.get("harm"))
    if harm:
        fields.append("injuries: " + harm)
    acts = format_acts(ep.get("acts"))
    if acts:
        fields.append("did: " + acts)
    if ep.get("slept"):
        fields.append("slept here")
    return " | ".join(fields)


def format_moodles(moodles: dict) -> str:
    items = []
    for key, level in as_dict(moodles).items():
        lv = as_int(level)
        if key in MOODLES and lv > 0:
            items.append(f"{MOODLES[key]} {lv}/4")
    return ", ".join(items)


def format_summary(summary: dict) -> list[str]:
    s = as_dict(summary)
    lines = [f"Day type: {DAY_TYPES.get(str(s.get('class')), 'unknown')}"]
    lines.append(
        f"Walked about {as_int(s.get('travel'))} tiles, at most {as_int(s.get('maxFromHome'))} tiles from home, "
        f"{as_int(s.get('outsideMin'))} minutes outdoors, killed {as_int(s.get('kills'))} zombies"
    )
    acts = format_acts(s.get("acts"))
    if acts:
        lines.append(f"Work and chores today: {acts}")
    moods = format_moodles(s.get("moodlePeaks"))
    if moods:
        lines.append(f"Strongest feelings today: {moods}")
    weather = clip(s.get("weather"), 60)
    if weather:
        lines.append(f"Weather: {weather}")
    return lines


NOTE_TEXT = {
    "storm": "a storm rolled in",
    "supply_drop_offered": "heard over the radio that {who} left supplies at {place}",
    "supply_drop_approached": "got close to the building where the supplies were left ({place})",
    "supply_drop_entered": "went into the building where the supplies were left ({place})",
    "supply_drop_completed": "{by} found the supplies at {place}",
    "supply_drop_failed": "never got to the supplies at {place} in time",
    "fetch_offered": "{who} asked over the radio for someone to bring back a {item} from {place}",
    "fetch_approached": "got close to the building where the {item} was ({place})",
    "fetch_entered": "went into the building where the {item} was ({place})",
    "fetch_retrieved": "{by} found the {item} at {place}",
    "fetch_completed": "{by} handed the {item} over to {who}",
    "fetch_failed": "failed to bring the {item} from {place} in time",
    "radio_contact": "talked over the radio with {who}",
    "deliver_proposed": "{who} asked over the radio for {item}",
    "deliver_accepted": "agreed to bring {item} to {who}",
    "deliver_declined": "turned down {who}'s request for {item}",
    "deliver_completed": "{by} handed {item} over to {who}",
    "deliver_failed": "failed to bring {item} to {who} in time",
    "horde_proposed": "{who} asked over the radio for help clearing a horde near {place}",
    "horde_accepted": "agreed to clear out the horde near {place} for {who}",
    "horde_declined": "refused {who}'s request to clear the horde near {place}",
    "horde_completed": "{by} cleared out the horde near {place} for {who}",
    "horde_failed": "never cleared the horde near {place} as promised to {who}",
    "horde_nearby": "a pack of about {count} of the dead came after them and would not stop following, and a radio contact warned them",
    "stay_horde": "they had stayed in one place too long; a pack of about {count} of the dead picked up their trail",
    "helicopter": "a helicopter flew low over the area, dragging the dead toward its noise",
    "rescue_offered": "{who} relayed a distress call from someone trapped at {place}",
    "rescue_approached": "got close to the building where the distress call came from ({place})",
    "rescue_entered": "went into the building where the distress call came from ({place})",
    "rescue_completed": "{by} reached the trapped survivor at {place}, too late; the survivor had turned, only their things were left",
    "rescue_failed": "never went to answer the distress call from {place}",
    "extort_demanded": "{who} threatened them over the radio, demanding {item}",
    "extort_completed": "{by} gave in to {who}'s threats and handed over {item}",
    "extort_failed": "never paid {who} what they demanded ({item})",
    "death_of": "heard that {by}, another survivor, had died near {place}",
    "extort_punished": "{who} made good on their threat and came after them (the dead or armed men)",
    "alife_support": "{who} sent {count} armed people who fought at their side for a few hours",
    "alife_attack": "{who} sent {count} armed men to hunt them down",
    "trade_accepted": "agreed to trade with {who} for {item}",
    "trade_completed": "{by} paid {who} and traded for {item}",
    "trade_failed": "backed out of a trade with {who} for {item}",
    # 이전 버전 세이브 호환
    "supply_offered": "heard that someone left supplies at {place}",
    "supply_approached": "got close to the building where the supplies were left ({place})",
    "supply_entered": "went into the building where the supplies were left ({place})",
    "supply_looted": "{by} found the supplies at {place}",
    "supply_expired": "never went for the supplies at {place}",
}


def faction_label(fid: Any, lang: Any) -> str:
    faction = FACTIONS.get(str(fid))
    if not faction:
        return ""
    local = faction["local"].get(str(lang or "").upper(), "")
    return f"{faction['name']} [{local}]" if local else faction["name"]


MAX_RADIO_LINES = 30


# 무전 교신 기록 (게임 Radio.logLine): 플레이어 자신의 말과 NPC 의 말. 플레이어 말은 발언으로만 다룬다.
def format_radio(lines: Any, lang: Any, writer: str, with_day: bool = False) -> list[str]:
    out = []
    for m in as_list(lines)[-MAX_RADIO_LINES:]:
        m = as_dict(m)
        text = clip(m.get("text"), 220)
        if not text:
            continue
        who = faction_label(m.get("faction"), lang) or (
            "everyone on the open channel" if m.get("faction") == "open" else "a radio contact")
        when = clip(m.get("clock"), 5)
        if with_day and as_int(m.get("day")):
            when = f"day {as_int(m.get('day'))} {when}"
        if m.get("from") == "player":
            out.append(f'- [{when}] {writer} to {who}: "{text}"')
        else:
            out.append(f'- [{when}] {who}: "{text}"')
    return out


def format_note(note: dict, lang: Any = None) -> str | None:
    note = as_dict(note)
    kind = str(note.get("kind"))
    if kind == "banter":
        spoken = [clip(line, 160) for line in as_list(note.get("lines"))[:4] if line]
        if not spoken:
            return None
        who = ", ".join(clip(n, NAME_LIMIT) for n in as_list(note.get("with"))[:3] if n) or "a companion"
        return f'{clip(note.get("clock"), 5)} talked with {who}: ' + " / ".join(f'"{x}"' for x in spoken)
    template = NOTE_TEXT.get(kind)
    if not template:
        return None
    who = faction_label(note.get("faction"), lang)
    if kind == "radio_contact" and not who:
        return None
    text = template.format(
        place=format_place(note.get("place"), lang) if note.get("place") else "an unknown place",
        who=who or "someone",
        by=clip(note.get("by"), NAME_LIMIT) or "someone",
        item=clip(note.get("item"), 40) or "package",
        count=as_int(note.get("count")) or "a few",
    )
    if kind == "death_of":
        together = as_int(note.get("together"))
        if together >= 60:
            text += f" (they had spent about {together // 60} hours in each other's company)"
        elif together > 0:
            text += " (they had only crossed paths briefly)"
        else:
            text += " (they had never met in person)"
    fight = as_dict(note.get("fight"))
    if fight:
        bits = []
        if as_int(fight.get("kills")):
            bits.append(f"killed {as_int(fight.get('kills'))} zombies there")
        if fight.get("bitten"):
            bits.append("someone was bitten")
        elif as_int(fight.get("hurt")):
            bits.append("someone got hurt")
        if bits:
            text += " (a fight: " + ", ".join(bits) + ")"
    return f"{clip(note.get('clock'), 5)} {text}".strip()


def format_character(ch: dict) -> str:
    ch = as_dict(ch)
    name = clip(ch.get("name"), 60) or "the survivor"
    prof = clip(ch.get("profession"), 40)
    return f"{name}" + (f", formerly a {prof}" if prof else "")


def build_journal(payload: dict, mcfg: dict) -> LLMRequest:
    kind = str(payload.get("kind", "daily"))
    code = str(payload.get("lang") or "EN").upper()
    lang = language_name(code)
    character = format_character(payload.get("character"))

    if kind == "memoir":
        lines = [f"Language: {lang}", f"Survivor: {character}",
                 f"Survived {as_int(payload.get('daysSurvived'))} days after the outbreak."]
        death = as_dict(payload.get("death"))
        if death:
            lines.append(f"Died on {clip(death.get('date'), 20)} at {format_place(death.get('place'), code)}"
                         + (f"; last injuries: {format_harm(death.get('harm'))}" if death.get("harm") else ""))
        weeks = [as_dict(w) for w in as_list(payload.get("weeks"))[-40:]]
        if weeks:
            lines.append("Earlier weeks, summarised:")
            for w in weeks:
                lines.append(f"- Days {as_int(w.get('from'))}-{as_int(w.get('to'))}: {clip(w.get('text'), 800)}")
        lines.append("Life after the outbreak, day by day:" if not weeks else "The last days, one by one:")
        for d in as_list(payload.get("days"))[-MAX_MEMOIR_DAYS:]:
            d = as_dict(d)
            entry = f"- Day {as_int(d.get('day'))} ({clip(d.get('date'), 20)}): {DAY_TYPES.get(str(d.get('class')), 'unknown')}"
            diary = clip(d.get("diary"), 400)
            if diary:
                entry += f". Their diary said: {diary}"
            lines.append(entry)
        for ep in as_list(payload.get("episodes"))[-10:]:
            lines.append(f"- Final hours: {format_episode(ep, code)}")
        name = clip(as_dict(payload.get("character")).get("name"), NAME_LIMIT) or "They"
        radio = format_radio(payload.get("radio"), code, name, with_day=True)
        if radio:
            lines.append("Their last radio conversations (what they actually said and heard):")
            lines.extend(radio)
        system = load_prompt("memoir")
    elif kind == "daily":
        episodes = as_list(payload.get("episodes"))[-MAX_EPISODES:]
        lines = [f"Language: {lang}", f"Writer: {character}",
                 f"Date: {clip(payload.get('date'), 20)} (day {as_int(payload.get('day'))} since the outbreak)"]
        home = payload.get("home")
        if isinstance(home, dict) and home:
            lines.append(f"Home: {format_place({**home, 'home': False}, code)}")
        lines.extend(format_summary(payload.get("summary")))
        lines.append("What happened since the last entry:")
        if episodes:
            lines.extend(f"- {format_episode(ep, code)}" for ep in episodes)
        else:
            lines.append("- Nothing was recorded.")
        notes = [n for n in (format_note(x, code) for x in as_list(payload.get("notes"))[:12]) if n]
        if notes:
            lines.append("Other things that happened:")
            lines.extend(f"- {n}" for n in notes)
        writer = clip(as_dict(payload.get("character")).get("name"), NAME_LIMIT) or "They"
        radio = format_radio(payload.get("radio"), code, writer)
        if radio:
            lines.append("What was actually said on the radio (the writer's own words and the replies they heard):")
            lines.extend(radio)
        weeks = [as_dict(w) for w in as_list(payload.get("weeks"))[-1:]]
        for w in weeks:
            lines.append(f"The week before, in brief (days {as_int(w.get('from'))}-{as_int(w.get('to'))}): "
                         f"{clip(w.get('text'), 800)}")
        previous = clip(payload.get("previous"), 400)
        if previous:
            lines.append(f"Previous diary entry (for continuity, do not repeat it): {previous}")
        system = load_prompt("journal")
    elif kind == "comment":
        # 다른 생존자의 죽음에 대한 짧은 추모 (회고록 아래 코멘트)
        dead = as_dict(payload.get("dead"))
        lines = [f"Language: {lang}", f"Writer: {character}",
                 f"The survivor who died: {format_character(dead)}, after {as_int(dead.get('daysSurvived'))} days, "
                 f"on {clip(dead.get('date'), 20)}"]
        place = dead.get("place")
        if isinstance(place, dict) and place:
            lines.append(f"Where they died: {format_place(place, code)}")
        harm = format_harm(dead.get("harm"))
        if harm:
            lines.append(f"Their last injuries: {harm}")
        together = as_int(payload.get("together"))
        if together >= 60:
            lines.append(f"The writer spent about {together // 60} hours in their company.")
        elif together > 0:
            lines.append("The writer crossed paths with them only briefly.")
        else:
            lines.append("The writer never spent time with them in person; they only knew of them.")
        mentions = [as_dict(m) for m in as_list(payload.get("mentions"))[:3]]
        if mentions:
            lines.append("What the writer's own diary said when the dead survivor came up:")
            for m in mentions:
                lines.append(f"- {clip(m.get('date'), 20)}: {clip(m.get('text'), 300)}")
        system = load_prompt("journal_comment")
    else:
        raise ModuleError("bad_payload")

    return LLMRequest(
        module="journal",
        model=str(mcfg.get("model", "mock")),
        system=system,
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 16000)),
        effort=mcfg.get("effort"),
    )


# ---------------------------------------------------------------- director

# 게임이 보낸 이벤트 id 중 여기 설명이 있는 것만 LLM 에 보여 준다 (양쪽 화이트리스트).
DIRECTOR_EVENTS = {
    "quiet_day": "Nothing special happens. Lets the survivors breathe.",
    "storm": "A thunderstorm rolls in for hours (intensity 1: 6h, 2: 12h, 3: 18h, 4: 24h, 5: 36h). Rain, wind and thunder "
             "that draws zombies; hard to travel.",
    "supply_drop": "A friendly radio contact leaves supplies in a building for the target and tells them where. "
                   "Intensity 1-5 sets both reward and distance: 1 = nearby (60-200 tiles), a little food, bandages "
                   "and one common tool or handgun with a few rounds; 2 = same neighbourhood, food, water, "
                   "painkillers, a decent tool and a melee weapon or handgun; 3 = edge of town, plenty of food, "
                   "medicine, a hunting rifle with ammo; 4 = the countryside 1000-2000 tiles out, "
                   "lots of food and water, antibiotics, a rare tool and a shotgun with shells; 5 = another town entirely, a "
                   "huge cache with an assault rifle, a sidearm and plenty of ammo. Deadlines grow with distance "
                   "(days to about two weeks). It fails if they do not collect it in time.",
    "npc_request": "A radio contact asks the target for help: either specific supplies they need right now "
                   "(medicine, food, tools, ammo), or clearing out a horde of the dead gathered around a building "
                   "(8 to 45 zombies by intensity), for a supply reward. The target can accept or refuse. Helping when a contact "
                   "asked builds trust in proportion to the tier (1 to 5); refusing, ignoring or failing costs some. Good when a survivor is "
                   "doing well and could share; intensity 1 asks for little, 5 for rare things.",
    "horde_nearby": "Every survivor online gets their own horde of the dead (20 early, 40 after a month, 60 after three "
                    "months) that starts 50-80 tiles away and follows them until it is killed; a radio contact warns "
                    "them. Very dangerous. Good when the group has been safe and idle for too long; avoid it right after a "
                    "hard day.",
    "helicopter": "A mysterious helicopter flies low over the area for a while. Its noise draws zombies from far "
                  "around toward it. Rare and ominous; it adds dread, not loot. Intensity does not matter.",
    "rescue_signal": "A radio contact relays a distress call: someone says they are trapped in a building (distance by "
                     "intensity, like supply_drop). When the target gets there, the survivor has already turned; a few "
                     "zombies wait inside with what they left behind (a supply cache). Good for pulling an idle or "
                     "bored survivor out of the house, with some danger.",
    "friend_gift": "A radio contact who trusts the target a lot sets aside a small supply cache for them without being "
                   "asked (low tier only). Rewards a good relationship.",
    "extortion": "A hostile radio contact (one who barely trusts them) threatens the target: hand over specific items "
                 "within 36 hours or they will lure a horde or a helicopter onto them. Paying ends it with a small "
                 "payment. Rare; only when a relationship has gone sour.",
    "fetch_item": "A radio contact asks the target to retrieve a sealed package from a building and report it "
                  "over the radio, for a supply reward. Same distance and reward scale as supply_drop. Gives a "
                  "bored or idle survivor a goal; fails if not delivered before the deadline.",
}
MAX_PLAYERS = 16


def format_director_player(p: dict) -> list[str]:
    p = as_dict(p)
    name = clip(p.get("name"), NAME_LIMIT)
    state = [f"health {as_int(p.get('hp'), 100)}/100"]
    if p.get("bitten"):
        state.append("BITTEN")
    wounds = as_int(p.get("wounds"))
    if wounds:
        state.append(f"{wounds} wounds")
    state.append("indoors" if p.get("inside") else "outdoors")
    town = clip(p.get("town"), 40)
    if town:
        state.append(f"near {town}")
    zombies = as_int(p.get("zombiesNear"))
    if zombies:
        state.append(f"{zombies} zombies within 30 tiles")
    moods = format_moodles(p.get("moodles"))
    if moods:
        state.append(moods)
    if p.get("activeQuest"):
        state.append("already has an unclaimed supply drop")
    stage = {1: "early days, has little", 2: "settling in", 3: "well established, well stocked"}.get(as_int(p.get("stage")))
    cap = as_int(p.get("maxIntensity"))
    if stage:
        state.append(stage)
    if cap:
        state.append(f"intensity at most {cap}")
    lines = [f"- {name}: " + ", ".join(state)]
    week = clip(p.get("lastWeek"), 400)
    if week:
        lines.append(f"    last full week: {week}")
    for d in as_list(p.get("days"))[-3:]:
        d = as_dict(d)
        lines.append(
            f"    day {as_int(d.get('day'))}: {DAY_TYPES.get(str(d.get('class')), 'unknown')}, "
            f"killed {as_int(d.get('kills'))}, {'injured' if d.get('harmed') else 'unhurt'}, "
            f"went {as_int(d.get('maxFromHome'))} tiles from home"
        )
    return lines


def build_director(payload: dict, mcfg: dict) -> LLMRequest:
    players = [as_dict(p) for p in as_list(payload.get("players"))[:MAX_PLAYERS]]
    names = []
    for p in players:
        n = clip(p.get("name"), NAME_LIMIT)
        if n and n not in names:
            names.append(n)
    if not names:
        raise ModuleError("no_players")
    events = []
    for e in as_list(payload.get("events")):
        eid = str(as_dict(e).get("id", ""))
        if eid in DIRECTOR_EVENTS and eid not in events:
            events.append(eid)
    if not events:
        raise ModuleError("no_events")

    weather = as_dict(payload.get("weather"))
    sky = "thunderstorm" if weather.get("thunder") else "raining" if weather.get("raining") else \
        "snowing" if weather.get("snowing") else "dry"
    lines = [
        f"Day {as_int(payload.get('day'))}, {clip(payload.get('date'), 10)} {clip(payload.get('clock'), 5)}. "
        f"Weather: {sky}, {as_int(weather.get('temp'))}C.",
        "Survivors:",
    ]
    for p in players:
        lines.extend(format_director_player(p))
    recent = as_list(payload.get("recent"))[-6:]
    lines.append("Recent decisions:" if recent else "Recent decisions: none yet.")
    for r in recent:
        r = as_dict(r)
        lines.append(f"- day {as_int(r.get('day'))} {clip(r.get('clock'), 5)}: {clip(r.get('event'), 30)} "
                     f"(intensity {as_int(r.get('intensity'), 1)}) for {clip(r.get('target'), NAME_LIMIT)}")
    lines.append("Events you can choose now:")
    lines.extend(f"- {e}: {DIRECTOR_EVENTS[e]}" for e in events)

    schema = {
        "type": "object",
        "properties": {
            "event": {"type": "string", "enum": events},
            "intensity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "target": {"type": "string", "enum": names},
            "reason": {"type": "string"},
        },
        "required": ["event", "intensity", "target", "reason"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="director",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("director"),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 16000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


# ---------------------------------------------------------------- radio

# 세력 페르소나. 게임(Lua)에는 id, 주파수, 거점 좌표만 있고 성격·말투는 여기서 관리한다.
FACTIONS = {
    "ray": {
        "name": "Ray Mercer",
        "local": {"KO": "레이 머서"},
        "who": "A former long-haul trucker in his fifties, holed up alone in a farmhouse outside West Point. "
               "Warm, talkative, lonely, a little too trusting. Low on supplies but has some canned food and "
               "a bit of medicine. Misses his daughter in Louisville. Talks like a Kentucky trucker.",
        "trust": "Starts friendly.",
        "speech": {"KO": "warm, easygoing speech of an older man: banmal mixed with 하게체 (자네, ~네, ~게, ~구먼)."},
    },
    "guard": {
        "name": "Sergeant Dale Whitaker",
        "local": {"KO": "데일 휘태커 병장"},
        "who": "Leader of what is left of a National Guard squad at the Knox Boundary Camp, north of Muldraugh "
               "near Louisville. Terse, uses radio procedure, follows orders that nobody gives anymore. "
               "Well armed but short on medicine and tools. Deeply suspicious of civilians, never careless "
               "with weapons or ammunition.",
        "trust": "Starts wary. Earns trust slowly and loses it fast.",
        "speech": {"KO": "stiff military 다나까 speech (~다, ~습니다, ~나?, ~까?). Never 해요체, never casual banmal."},
    },
    "rats": {
        "name": "Vic",
        "local": {"KO": "빅"},
        "who": "Leader of a scavenger crew calling themselves the Coalfield Crew, working out of the old "
               "mining area near Coalfield, west of Fallas Lake. Sarcastic, greedy, practical. Has picked "
               "the county clean and has a bit of everything, for a price. Not a murderer over the radio, "
               "but always looking for an angle.",
        "trust": "Starts cold. Respects toughness and good deals, not politeness.",
        "speech": {"KO": "rough, sarcastic banmal with everyone (~냐, ~지, ~거든, ~해라)."},
    },
    "casey": {
        "name": "Casey Liu",
        "local": {"KO": "케이시 리우"},
        "who": "A sixteen-year-old ham radio operator broadcasting from their father's radio shack in Valley Station, "
               "north of West Point. Their father is sick in bed. Bright, nervous, talks fast, loves electronics and "
               "radio jargon, and is desperate for someone to talk to. Knows batteries, radios, generators and wiring. "
               "Tries to sound older than they are.",
        "trust": "Starts eager and friendly, but gets scared and closes up if anyone sounds threatening.",
        "speech": {"KO": "polite 해요체 toward adults, a bit breathless (~요, ~거든요, ~잖아요). Never banmal."},
        "trade_tiers": {
            "tools": ["a few batteries or a flashlight", "a walkie-talkie or radio with batteries",
                      "electronics parts, wire and a manual, or a better walkie-talkie",
                      "a ham radio, or an amplifier with a pile of parts", "a generator, or a full radio kit"],
        },
    },
    "doc": {
        "name": "June Adler",
        "local": {"KO": "준 애들러"},
        "who": "A former ER nurse in her forties who keeps a small clinic running in Riverside, caring for a handful "
               "of wounded survivors. Calm, direct, exhausted, dry sense of humour. Rations medicine carefully and "
               "asks clinical questions about injuries. Will not waste supplies on people who lie to her.",
        "trust": "Starts polite but guarded. Warms to people who are honest and look after others.",
        "speech": {"KO": "calm, polite 존댓말 (합쇼체 and 해요체: ~습니다, ~세요, ~해요). Colder or warmer with trust, but never banmal."},
        "trade_tiers": {
            "medical": ["bandages and wipes", "bandages, painkillers, disinfectant and tweezers",
                        "antibiotics with a suture kit", "a surgical kit with antibiotics, splints and a scalpel",
                        "a full medical bag"],
        },
    },
    "pike": {
        "name": "Brother Amos Pike",
        "local": {"KO": "에이머스 파이크 목사"},
        "who": "A lay preacher in his sixties who opened the church in March Ridge to refugees and now feeds a small "
               "congregation. Gentle, patient, speaks in a slow Kentucky drawl and quotes scripture now and then. "
               "Believes in charity and asks less than things are worth. Quietly firm with anyone who threatens his flock.",
        "trust": "Starts kind but careful. Trust grows when players help others, not only themselves.",
        "speech": {"KO": "gentle, slow 존댓말 (~습니다, ~지요, ~시오); may call them 형제님 or 자매님."},
    },
    "dewey": {
        "name": "Dewey Hollis",
        "local": {"KO": "듀이 홀리스"},
        "who": "A mechanic in his thirties living in his garage in Echo Creek, surrounded by half-fixed cars. "
               "Friendly in a gruff way, talks about engines constantly, swears when things go wrong. Trades car parts "
               "and tools and dreams of building a truck that can get people out of the county.",
        "trust": "Starts neutral. Likes people who keep their word and can fix things.",
        "speech": {"KO": "gruff, friendly banmal (~야, ~지, ~거든, ~냐)."},
        "trade_tiers": {
            "tools": ["a screwdriver or wrench", "a lug wrench and jack, or a tire pump",
                      "engine parts or a car battery", "a better car battery with engine parts, or a welding kit",
                      "a heavy-duty battery, lots of engine parts and a manual, or a full welding setup"],
        },
    },
    "hunter": {
        "name": "Hank Tolliver",
        "local": {"KO": "행크 톨리버"},
        "who": "An old trapper and hunter living alone in a cabin in the woods near Ekron. Few words, suspicious of "
               "everyone, lived off the land long before the outbreak. Knows rifles, knives, traps and dried meat. "
               "Has no patience for fools or talkers.",
        "trust": "Starts at zero. Barely answers strangers. Only deeds earn his respect.",
        "speech": {"KO": "very short, gruff banmal (~다, ~냐, ~해라)."},
        "trade_tiers": {
            "firearm": ["an old snub revolver with a few rounds", "a .357 or .44 revolver with a box of ammo",
                        "a hunting rifle (.308 or .30-30) with a box", "a scoped hunting rifle or a double-barrel shotgun with ammo"],
            "melee": ["a kitchen knife", "a hunting knife", "a hatchet and a hunting knife", "a wood axe or a machete"],
            "food": ["some jerky", "jerky and water", "a stock of dried meat and water"],
        },
    },
}
MAX_HISTORY = 16
TRADE_CATEGORIES = ["firearm", "ammo", "tools", "medical", "melee", "food"]
# counter / withdraw 는 답을 기다리는 제안을 흥정할 때만 쓴다
TRADE_ACTIONS = ["none", "offer", "refuse", "gift", "counter", "withdraw"]
# 등급별 거래 물건 안내 (게임 Trade.lua GOODS 와 맞춘다)
TRADE_TIERS = {
    "food": ["a few cans", "cans and water for a couple of days", "food and water for most of a week",
             "a big stock of food and water", "enough food and water for weeks"],
    "medical": ["some bandages", "bandages, painkillers and disinfectant", "bandages, disinfectant and antibiotics",
                "a surgical kit with antibiotics, sutures and a splint", "a full field hospital kit"],
    "tools": ["a screwdriver, saw or hammer", "a crowbar, wrench or hand axe", "two good tools",
              "a sledgehammer, wood axe or blowtorch", "two rare heavy tools"],
    "melee": ["a kitchen knife or bat", "a hunting knife or bat", "a machete or crowbar", "a katana or axe",
              "a katana and a machete"],
    "firearm": ["a 9mm pistol or .38 revolver with a dozen rounds", "a .45, .357 or .44 handgun with a box of ammo",
                "a hunting rifle (.308 or .30-30) with ammo", "a shotgun with two boxes of shells",
                "a military rifle or automatic weapon with plenty of ammo, plus a sidearm"],
    "ammo": ["a couple dozen loose rounds", "one box of ammo", "two boxes of ammo",
             "three boxes of shotgun or rifle ammo", "eight boxes of rifle ammo"],
}


def tier_name(fid: str, cat: str, tier: int) -> str:
    names = FACTIONS.get(fid, {}).get("trade_tiers", {}).get(cat, TRADE_TIERS.get(cat, []))
    return names[tier - 1] if 1 <= tier <= len(names) else f"{cat} tier {tier}"


# 답을 기다리는 거래 제안에 대한 흥정 (게임 Trade.negotiate 가 하한선·횟수를 다시 검증한다)
def format_haggle_rules(trade: dict, fid: str = "") -> list[str]:
    deal = as_dict(trade.get("deal"))
    cat = str(deal.get("category"))
    tier = as_int(deal.get("tier"))
    price = as_int(deal.get("price"))
    base = as_int(deal.get("basePrice"), price)
    floor = as_int(trade.get("floor"), price)
    pay = str(deal.get("payCategory"))
    left = as_int(trade.get("haggleLeft"))
    wants = [w for w in as_list(trade.get("wants")) if w in TRADE_CATEGORIES]
    first = f" (your first asking price was {base})" if base != price else ""
    lines = [
        "Trading rules (from the game, you must follow them):",
        f"- You already offered them {tier_name(fid, cat, tier)} ({cat}, tier {tier}) for payment in {pay} "
        f"worth {price} value points{first}. They have not accepted or declined yet.",
        "- Make no new offer until this deal is settled. If they ask for something else, tell them to settle this "
        "one first.",
    ]
    if left > 0:
        lines += [
            f"- They may haggle: ask for a lower price, or offer to pay in another category you accept "
            f"({', '.join(wants) or pay}). Your lowest price is {floor} value points; the game never goes lower. "
            f"Haggling rounds left: {left}.",
            "- Decide in character how far you move: take their price if it is at or above your lowest, meet them "
            "halfway, or hold firm. Give ground step by step over the rounds; do not drop straight to your lowest "
            "price, least of all for an insulting offer. To change the terms use action \"counter\" with the new \"price\" and "
            "\"pay_category\" (keep the deal's category and tier). To keep the terms use action \"none\".",
            "- While haggling you may say the price in your reply.",
        ]
    else:
        lines.append("- No more haggling: you have moved as far as you will. Keep the terms (action \"none\"), "
                     "or call off the deal (action \"withdraw\") if they keep pushing.")
    lines.append("- If their offer is insulting (far below your lowest price) or they are rude about it, you may lower "
                 "trust by 1 and you may call off the deal with action \"withdraw\".")
    return lines


def format_trade_rules(trade: dict, fid: str = "") -> list[str]:
    trade = as_dict(trade)
    special = FACTIONS.get(fid, {}).get("trade_tiers", {})
    if trade.get("negotiating"):
        return format_haggle_rules(trade, fid)
    if not trade.get("allowed"):
        reason = str(trade.get("reason", ""))
        if reason == "low_trust":
            need = as_int(trade.get("need"), 20)
            return ["Trading rules: you will not trade with these players at all right now; you do not trust them. "
                    "Refuse any request for goods, in character (action \"refuse\" with the category and tier they "
                    f"asked for), and make clear you do not trade with people you do not trust yet. "
                    f"(You would start trading at trust {need}.)"]
        if reason == "open_deal":
            return ["Trading rules: there is already an unfinished deal (their group shares deals, so it may be one "
                    "a companion made, with you or another contact). Tell them to finish that one first "
                    "and do not make a new offer."]
        return ["Trading rules: do not offer any trade in this message."]
    lines = ["Trading rules (from the game, you must follow them):"]
    goods = []
    for g in as_list(trade.get("goods")):
        g = as_dict(g)
        cat = str(g.get("category"))
        top = max(0, min(5, as_int(g.get("maxTier"))))
        if cat in TRADE_TIERS and top > 0:
            goods.append((cat, top))
    lines.append("- What you can offer now (category up to tier): " +
                 ", ".join(f"{cat} up to {top}" for cat, top in goods))
    catalog = []
    for c in as_list(trade.get("catalog")):
        c = as_dict(c)
        cat = str(c.get("category"))
        if cat in TRADE_TIERS:
            catalog.append((cat, max(0, as_int(c.get("maxTier"))), [as_int(n, 101) for n in as_list(c.get("needs"))]))
    if catalog:
        # 취급하는 모든 등급을 보여 주고, 아직 못 주는 등급은 필요한 신뢰도와 함께 잠김으로 표시한다
        for cat, top, needs in catalog:
            names = special.get(cat, TRADE_TIERS[cat])
            tiers = []
            for i, need in enumerate(needs[:len(names)]):
                if i + 1 <= top:
                    tiers.append(f"{i + 1} = {names[i]}")
                elif need <= 100:
                    tiers.append(f"{i + 1} = {names[i]} (locked: needs trust {need})")
            lines.append(f"  {cat}: " + "; ".join(tiers))
        never = [c for c in TRADE_CATEGORIES if c not in {cat for cat, _, _ in catalog}]
        if never:
            lines.append("- You never trade: " + ", ".join(never))
        lines.append("- If they clearly ask for something locked, or anything above what you can offer now, do NOT "
                     "offer something smaller in its place. Refuse with action \"refuse\", putting the category and "
                     "tier they asked for, and tell them plainly that it takes more trust than they have earned "
                     "(or that you never deal in it). They can ask for something smaller themselves.")
    else:
        for cat, top in goods:
            names = special.get(cat, TRADE_TIERS[cat])
            top = min(top, len(names))
            tiers = "; ".join(f"{i + 1} = {names[i]}" for i in range(top))
            lines.append(f"  {cat}: {tiers}")
    wants = [w for w in as_list(trade.get("wants")) if w in TRADE_CATEGORIES]
    lines.append("- Payment you accept: " + (", ".join(wants) or "none"))
    recent = as_int(trade.get("recentRequests"))
    if recent:
        lines.append(f"- They have already asked you for goods {recent} times in the past week.")
    if trade.get("suspicious"):
        lines.append("- They are asking far too often. You are getting suspicious that they are using you: say that "
                     "you noticed, and you may refuse or demand a stiffer price.")
    free = as_int(trade.get("freeMaxTier"))
    if free:
        lines.append(f"- This time you feel generous because you trust them: if what they ask for is small (tier {free} "
                     "or lower), give it for nothing with action \"gift\" instead of \"offer\", and say it is on you. "
                     "For bigger things, make a normal offer.")
    mult = trade.get("mult")
    note = f"x{mult} of the goods' value at this trust" if mult else "the goods' value"
    if trade.get("stretchMult"):
        note += f"; tiers above {as_int(trade.get('maxTier'))} cost x{trade.get('stretchMult')} more"
    lines.append(f"- The game sets the exact price: {note}.")
    return lines
# 신뢰도 구간별 태도. 세력 고유의 성격 위에 얹는다.
TRUST_TONES = [
    (20, "You distrust them deeply. Be curt, cold and suspicious. Give nothing away, answer in as few words as "
         "possible, and you may warn them off or end the call."),
    (40, "You are wary of them. Keep answers short and guarded, share nothing personal, and question their motives."),
    (60, "You are neutral. Polite and businesslike, cautiously open to working with them."),
    (80, "You like them. Be warmer, use their names, share news and your own worries, and show you care what "
         "happens to them."),
    (101, "They are trusted friends. Be open and warm, joke with them, worry about them, and go out of your way "
          "to help them."),
]


def trust_tone(trust: int) -> str:
    for limit, tone in TRUST_TONES:
        if trust < limit:
            return tone
    return TRUST_TONES[-1][1]


# 공용 주파수 장면용 3인칭 태도 (TRUST_TONES 와 같은 구간)
TRUST_ATTITUDES = [
    (20, "distrusts the players deeply: curt, cold and suspicious with them"),
    (40, "is wary of the players: short, guarded, questions their motives"),
    (60, "is neutral toward the players: polite and businesslike"),
    (80, "likes the players: warm, uses their names, cares what happens to them"),
    (101, "treats the players as trusted friends: open, warm, joking, protective"),
]


def trust_attitude(trust: int) -> str:
    for limit, text in TRUST_ATTITUDES:
        if trust < limit:
            return text
    return TRUST_ATTITUDES[-1][1]


def trust_word(trust: int) -> str:
    for limit, word in ((20, "not at all"), (40, "a little"), (60, "somewhat"), (80, "a lot")):
        if trust < limit:
            return word
    return "completely"


# 게임 Social.context: 이 NPC 의 이야기, 다른 NPC 에 대한 생각, 들은 소식
def format_story_context(story: Any) -> list[str]:
    story = as_dict(story)
    out = []
    beat = clip(story.get("beat"), 400)
    if beat:
        out.append(f"What is going on in your own life right now: {beat}")
    past = [clip(x, 300) for x in as_list(story.get("past"))[-3:] if x]
    if past:
        out.append("Earlier in your life since the outbreak: " + " ".join(past))
    others = []
    for o in as_list(story.get("others"))[:6]:
        o = as_dict(o)
        f = FACTIONS.get(str(o.get("id")))
        note = clip(o.get("note"), 200)
        if not f or not note:
            continue
        line = f"{f['name']}: {note}"
        trust = as_int(o.get("trust"), -1)
        if trust >= 0:
            line += f"; how much they (not you) trust the players: {trust_word(trust)}"
        obeat = clip(o.get("beat"), 220)
        if obeat:
            line += f'; their situation lately, in their own words ("you" means them): {obeat}'
        others.append("- " + line)
    if others:
        out.append("Other people on the radio you know (mention them when it comes up naturally):")
        out.extend(others)
    news = [clip(x, 300) for x in as_list(story.get("news"))[-3:] if x]
    if news:
        out.append("Things you have heard lately: " + " ".join(news))
    return out


FOLLOW_UP_HOURS = [0, 1, 2, 3, 4, 6, 8, 12, 24]
MAX_MESSAGE = 240


def build_radio(payload: dict, mcfg: dict) -> LLMRequest:
    fid = str(payload.get("faction", ""))
    faction = FACTIONS.get(fid)
    if not faction:
        raise ModuleError("unknown_faction")
    code = str(payload.get("lang") or "EN").upper()
    local_name = faction["local"].get(code, "")
    name = f"{faction['name']} ({local_name})" if local_name else faction["name"]

    trust = max(0, min(100, as_int(payload.get("trust"), 50)))
    persona = [
        f"You are: {name}. {faction['who']}",
        f"How you treat strangers at first (only matters before trust is built): {faction['trust']}",
        f"Current trust in these players: {trust}/100.",
        f"Your attitude toward them right now: {trust_tone(trust)} This follows the trust number only; do not "
        "drift warmer or colder than this because of the log, your memories or other people's feelings. Keep "
        "your own personality; the attitude changes how much warmth and openness you show, not who you are.",
    ]
    speech = faction.get("speech", {}).get(code)
    if speech:
        persona.append(f"Your speech level in {language_name(code)}: {speech} Use this same speech level in every "
                       "message, whatever the trust and whatever earlier lines in the log used; trust changes warmth, "
                       "not speech level.")
    memory = clip(payload.get("memory"), 1000)
    if memory:
        persona.append(f"What you remember from earlier talks: {memory}")
    persona.extend(format_story_context(payload.get("story")))

    lines = [
        f"Language: {language_name(code)}",
        f"Day {as_int(payload.get('day'))}, {clip(payload.get('date'), 10)} {clip(payload.get('clock'), 5)}.",
    ]
    players = [clip(p, NAME_LIMIT) for p in as_list(payload.get("players"))[:MAX_PLAYERS] if p]
    if players:
        lines.append("Players on the frequency: " + ", ".join(players))
    lines.append("Radio log (oldest first):")
    history = as_list(payload.get("history"))[-MAX_HISTORY:]
    for m in history:
        m = as_dict(m)
        speaker = faction["name"] if m.get("from") == "npc" else clip(m.get("name"), NAME_LIMIT) or "someone"
        if m.get("auto"):
            # 게임이 대신 보낸 소식. 플레이어는 자기 언어로 받았고, 기록에는 영어 요약만 있다
            speaker += " (a message you sent; the players received it in their language, English summary here)"
        lines.append(f"[{clip(m.get('clock'), 5)}] {speaker}: {clip(m.get('text'), MAX_MESSAGE)}")
    if not history:
        lines.append("(nothing yet)")
    mode = payload.get("mode")
    topic = clip(payload.get("topic"), 300)
    if not mode:
        lines.extend(format_trade_rules(payload.get("trade"), fid))
    if mode == "follow_up":
        lines.append(f"Nobody has called you. You are calling them back yourself about: {topic or 'what you promised to check'}")
        lines.append(f"Now start the call as {faction['name']}.")
    elif mode == "event":
        lines.append(f"Something just happened: {topic}")
        lines.append(f"Now start the call as {faction['name']} and react to it.")
    elif mode == "request":
        lines.append(f"You need help: {topic}")
        lines.append(f"Now start the call as {faction['name']} and ask for it.")
    elif mode == "chat":
        lines.append(f"Nobody has called you. You are calling them yourself, just to talk: {topic}")
        lines.append(f"Now start the call as {faction['name']}.")
    elif mode == "crisis":
        lines.append(f"Something is happening and you need their help, but others need it too: {topic}")
        lines.append(f"Now start the call as {faction['name']} and ask them to choose to help you.")
    else:
        lines.append(f"Now answer as {faction['name']}.")
    lines.append(f"Speak only {language_name(code)}, even if some lines above are in English. "
                 "Do not mix in English words, except radio words like \"over\" when natural.")

    schema = {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "trust_change": {"type": "integer", "enum": [-1, 0, 1]},
            "follow_up_hours": {"type": "integer", "enum": FOLLOW_UP_HOURS},
            "follow_up_topic": {"type": "string"},
            "trade": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": TRADE_ACTIONS},
                    "category": {"type": "string", "enum": TRADE_CATEGORIES + ["none"]},
                    "tier": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]},
                    "pay_category": {"type": "string", "enum": TRADE_CATEGORIES + ["none"]},
                    "price": {"type": "integer"},
                },
                "required": ["action", "category", "tier", "pay_category", "price"],
                "additionalProperties": False,
            },
        },
        "required": ["reply", "trust_change", "follow_up_hours", "follow_up_topic", "trade"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="radio",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("radio") + "\n\n" + "\n".join(persona),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 16000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


# ---------------------------------------------------------------- monologue

# 게임 Monologue.lua 의 TRIGGERS 와 같은 목록. 없는 계기는 거절한다.
MONOLOGUE_TRIGGERS = {
    "bitten": "They were just bitten on the {part}. They know what a bite means.",
    "low_health": "They are badly hurt and weak; their health just dropped dangerously low.",
    "first_kill": "They just killed a zombie for the first time.",
    "kills": "They just reached {kills} zombie kills since the outbreak.",
    "wounded": "They just got hurt: {wound} on the {part}.",
    "wake": "They just woke up.",
    "new_town": "They just arrived in {town} for the first time since the outbreak.",
    "supply_found": "They just picked up the last of the supplies left for them near {town}{source}. A small win.",
    "horde_cleared": "They just finished clearing out a pack of the dead around a building near {town}{source}. Exhausted, maybe relieved.",
    "storm": "The sky is darkening; a heavy storm is rolling in.",
    "helicopter": "A helicopter just roared low overhead, and it is not landing. The noise will draw the dead.",
    "panic": "Panic is rising{level}.",
    "pain": "The pain is getting worse{level}.",
    "sick": "They feel sick and feverish{level}.",
    "stress": "Their nerves are frayed{level}.",
    "unhappy": "They feel low and hopeless{level}.",
    "bored": "They are bored out of their mind{level}.",
    "hungry": "They are getting hungry{level}.",
    "thirsty": "They are getting thirsty{level}.",
    "tired": "They are getting tired{level}.",
}
LEVEL_WORDS = {2: " (noticeably)", 3: " (badly)", 4: " (overwhelmingly)"}
MAX_MONO_LINES = 5
MAX_SAID = 8


def format_trigger(trigger: str, info: dict, lang: Any) -> str:
    info = as_dict(info)
    template = MONOLOGUE_TRIGGERS[trigger]
    faction = faction_label(info.get("faction"), lang)
    source = ""
    if trigger == "supply_found":
        source = f", left by {faction}" if faction else ""
        if info.get("reward"):
            source += ", as payment for their help"
    elif trigger == "horde_cleared" and faction:
        source = f", as {faction} asked"
    town = clip(info.get("town"), 40)
    return template.format(
        part=BODY_PARTS.get(str(info.get("part")), "body"),
        wound=WOUNDS.get(str(info.get("kind")), "a wound"),
        kills=as_int(info.get("kills")),
        town=with_local(town, lang) if town else "a nearby town",
        level=LEVEL_WORDS.get(as_int(info.get("level")), ""),
        source=source,
    )


def build_monologue(payload: dict, mcfg: dict) -> LLMRequest:
    trigger = str(payload.get("trigger", ""))
    if trigger not in MONOLOGUE_TRIGGERS:
        raise ModuleError("unknown_trigger")
    code = str(payload.get("lang") or "EN").upper()
    count = max(1, min(MAX_MONO_LINES, as_int(payload.get("count"), 1)))

    lines = [
        f"Language: {language_name(code)}",
        f"Character: {format_character(payload.get('character'))}",
    ]
    # 여러 줄은 나중에 다른 때 다시 쓰이므로 그때와 어긋날 수 있는 시각·장소·날씨·최근 사건은 넘기지 않는다
    pooled = count > 1
    if not pooled:
        lines.append(f"Day {as_int(payload.get('day'))} after the outbreak, {clip(payload.get('clock'), 5)}.")
        lines.append(f"Where: {format_place(payload.get('place'), code)}")
        weather = as_dict(payload.get("weather"))
        sky = [w for w, key in (("rain", "raining"), ("snow", "snowing"), ("thunder", "thunder")) if weather.get(key)]
        if sky:
            lines.append("Weather: " + ", ".join(sky))
    health = as_int(payload.get("health"), 100)
    if health < 80:
        lines.append("Physically: " + ("badly hurt" if health < 45 else "hurt"))
    moods = format_moodles(payload.get("moodles"))
    if moods:
        # 수치는 모델이 문장에 옮기지 않도록 단어로만 넘긴다
        lines.append("Feeling: " + ", ".join(m.split(" ")[0] for m in moods.split(", ")))
    notes = [n for n in (format_note(x, code) for x in as_list(payload.get("notes"))[-4:]) if n]
    if notes and not pooled:
        lines.append("Recently: " + "; ".join(notes))
    diary = clip(payload.get("diary"), 400)
    if diary:
        lines.append(f"What they wrote in their diary last night: {diary}")
    said = [clip(x, 120) for x in as_list(payload.get("said"))[-MAX_SAID:] if x]
    if said:
        lines.append("Lines they said recently (do not repeat): " + " / ".join(said))
    lines.append(f"What just happened: {format_trigger(trigger, payload.get('info'), code)}")
    if pooled:
        lines.append(f"Write {count} lines. They will be used one at a time on later occasions, so keep them "
                     "free of time of day, place, weather and recent events.")
    else:
        lines.append("Write 1 line. Focus on what just happened; use at most one detail from the situation.")

    schema = {
        "type": "object",
        "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
        "required": ["lines"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="monologue",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("monologue"),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 2000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
        extra={"mock": {"lines": [f"[mock] {trigger} {i + 1}" for i in range(count)]}},
    )


# ---------------------------------------------------------------- summary (스토리 로그 압축)

MAX_SUMMARY_DAYS = 10
MAX_MEMORY_LINES = 40


def build_summary(payload: dict, mcfg: dict) -> LLMRequest:
    kind = str(payload.get("kind", ""))
    if kind == "week":
        lines = [f"Survivor: {format_character(payload.get('character'))}", "Days:"]
        for d in as_list(payload.get("days"))[:MAX_SUMMARY_DAYS]:
            d = as_dict(d)
            entry = (f"- Day {as_int(d.get('day'))} ({clip(d.get('date'), 20)}): "
                     f"{DAY_TYPES.get(str(d.get('class')), 'unknown')}, killed {as_int(d.get('kills'))}"
                     + (", injured" if d.get("harmed") else ""))
            diary = clip(d.get("diary"), 400)
            if diary:
                entry += f". Diary: {diary}"
            lines.append(entry)
        system = load_prompt("summary_week")
    elif kind == "radio_memory":
        faction = FACTIONS.get(str(payload.get("faction", "")))
        if not faction:
            raise ModuleError("unknown_faction")
        lines = [f"You are: {faction['name']}. {faction['who']}"]
        previous = clip(payload.get("previous"), 1500)
        lines.append(f"Your notes so far: {previous}" if previous else "Your notes so far: (none yet)")
        lines.append("Older radio log to fold in (oldest first):")
        for line in as_list(payload.get("lines"))[-MAX_MEMORY_LINES:]:
            lines.append(clip(line, 260))
        system = load_prompt("radio_memory")
    else:
        raise ModuleError("bad_payload")
    return LLMRequest(
        module="summary",
        model=str(mcfg.get("model", "mock")),
        system=system,
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 4000)),
        effort=mcfg.get("effort"),
    )


# ---------------------------------------------------------------- open channel scene

MAX_SCENE_LINES = 6


def build_radio_scene(payload: dict, mcfg: dict) -> LLMRequest:
    code = str(payload.get("lang") or "EN").upper()
    parts = []
    for x in as_list(payload.get("participants"))[:3]:
        x = as_dict(x)
        if str(x.get("id")) in FACTIONS:
            parts.append(x)
    ids = [str(x.get("id")) for x in parts]
    if len(ids) < 2:
        raise ModuleError("bad_payload")
    lines = [
        f"Language: {language_name(code)}",
        "Open radio channel 121.5: everyone on the air can hear.",
        f"Day {as_int(payload.get('day'))} after the outbreak, {clip(payload.get('clock'), 5)}.",
        "People on the channel (use these ids as speaker):",
    ]
    for x in parts:
        fid = str(x.get("id"))
        f = FACTIONS[fid]
        local = f["local"].get(code, "")
        name = f"{f['name']} ({local})" if local else f["name"]
        bits = [f"- {fid} = {name}. {f['who']}"]
        beat = clip(x.get("beat"), 300)
        if beat:
            bits.append(f'Their situation now, in their own words ("you" means them): {beat}')
        bits.append(f"Toward the players this person {trust_attitude(max(0, min(100, as_int(x.get('trust'), 30))))}.")
        speech = f.get("speech", {}).get(code)
        if speech:
            bits.append(f"Speech level, always the same: {speech}")
        rels = []
        for r in as_list(x.get("relations"))[:3]:
            r = as_dict(r)
            other = FACTIONS.get(str(r.get("id")))
            if other and r.get("note"):
                rels.append(f"about {other['name']}: {clip(r.get('note'), 200)}")
        if rels:
            bits.append("What they think of the others here: " + "; ".join(rels) + ".")
        lines.append(" ".join(bits))
    players = [clip(pl, NAME_LIMIT) for pl in as_list(payload.get("players"))[:MAX_PLAYERS] if pl]
    if players:
        lines.append("Players listening: " + ", ".join(players))
    lines.append("Recent talk on the open channel (oldest first):")
    log = as_list(payload.get("log"))[-12:]
    for m in log:
        m = as_dict(m)
        text = clip(m.get("text"), MAX_MESSAGE)
        if not text:
            continue
        if m.get("from") == "player":
            who = f"{clip(m.get('name'), NAME_LIMIT) or 'a player'} (a player)"
        else:
            who = FACTIONS.get(str(m.get("npc")), {}).get("name", "someone")
        lines.append(f'[{clip(m.get("clock"), 5)}] {who}: "{text}"')
    if not log:
        lines.append("(nothing yet)")
    said = as_dict(payload.get("said"))
    if said.get("text"):
        lines.append(f'{clip(said.get("name"), NAME_LIMIT) or "A player"} (one of the players) just said on the open channel: '
                     f'"{clip(said.get("text"), MAX_MESSAGE)}"')
        interrupted = clip(payload.get("interrupted"), 400)
        if interrupted:
            lines.append(f"The player cut into a conversation that was still going on. It was about: {interrupted}")
        lines.append("Those who would react answer the player first, each in their own way, then they react to each other.")
    else:
        lines.append(f"What they talk about now: {clip(payload.get('topic'), 400) or 'small talk'}")
    lines.append(f"Write 3 to {MAX_SCENE_LINES} lines. Speak only {language_name(code)}. "
                 "Do not mix in English words, except radio words like \"over\" when natural.")
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"speaker": {"type": "string", "enum": ids}, "text": {"type": "string"}},
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["lines"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="radio_scene",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("radio_scene"),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 4000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


# ---------------------------------------------------------------- banter

# 캐릭터끼리의 대화 계기. 혼잣말 계기(MONOLOGUE_TRIGGERS)는 "{who}에게 일어난 일"로 쓴다.
BANTER_EVENTS = {
    "chat": "Nothing in particular is happening; they are just spending time together.",
    "fight": "They just fought side by side and put down about {count} of the dead together. It has gone quiet.",
    "horde_near": "A pack of about {count} of the dead is hunting {who} down and is getting close.",
    "armed_attack": "Armed men sent by {faction} are closing in on {who}.",
    "support_arrived": "{count} armed people sent by {faction} just showed up to back them up.",
    "support_left": "The armed people {faction} sent to back them up are heading home.",
    "quest_accepted": "{who} just agreed to {what} for {faction}.",
    "quest_completed": "They just finished {what}{for_faction}.",
    "quest_failed": "They ran out of time on {what}{for_faction}.",
    "radio": "{who} just talked with {faction} on the radio, who answered: \"{text}\"",
    "death": "They just heard that {name}, another survivor, has died.",
}
MAX_BANTER_LINES = 4


def format_banter_event(event: dict, code: str) -> str:
    event = as_dict(event)
    kind = str(event.get("kind"))
    info = as_dict(event.get("info"))
    who = clip(event.get("who"), NAME_LIMIT) or "one of them"
    if kind in MONOLOGUE_TRIGGERS:
        return f"This just happened to {who}: " + format_trigger(kind, info, code)
    template = BANTER_EVENTS.get(kind)
    if not template:
        raise ModuleError("unknown_event")
    faction = faction_label(info.get("faction"), code)
    return template.format(
        who=who, count=as_int(info.get("count")) or "several", faction=faction or "a radio contact",
        for_faction=f" for {faction}" if faction else "", what=clip(info.get("what"), 80) or "a job",
        text=clip(info.get("text"), 200), name=clip(info.get("name"), NAME_LIMIT) or "someone",
    )


def build_banter(payload: dict, mcfg: dict) -> LLMRequest:
    speakers = [as_dict(x) for x in as_list(payload.get("speakers"))[:3]]
    names = [clip(x.get("name"), NAME_LIMIT) for x in speakers if clip(x.get("name"), NAME_LIMIT)]
    if len(names) < 2:
        raise ModuleError("bad_payload")
    langs = {str(x.get("lang") or "EN").upper() for x in speakers}
    code = next(iter(langs)) if len(langs) == 1 else "EN"
    lines = []
    if len(langs) == 1:
        lines.append(f"Language: everyone speaks {language_name(code)}")
    else:
        lines.append("Language: each person speaks their own language: " + ", ".join(
            f"{clip(x.get('name'), NAME_LIMIT)} speaks {language_name(str(x.get('lang') or 'EN').upper())}" for x in speakers))
    lines.append("Speakers:")
    for x in speakers:
        bits = [format_character(x)]
        hp = as_int(x.get("hp"), 100)
        if hp < 45:
            bits.append("badly hurt")
        elif hp < 80 or as_int(x.get("wounds")):
            bits.append("hurt")
        moods = format_moodles(x.get("moodles"))
        if moods:
            bits.append("feeling " + ", ".join(m.split(" ")[0] for m in moods.split(", ")))
        known = []
        for m in as_list(x.get("met"))[:3]:
            m = as_dict(m)
            hours = as_int(m.get("minutes")) // 60
            other = clip(m.get("name"), NAME_LIMIT)
            if other:
                known.append(f"has spent about {hours} hours in total with {other} since they met (not in one stretch)"
                             if hours else f"has barely spent time with {other}")
        if known:
            bits.append("; ".join(known))
        lines.append("- " + "; ".join(bits))
    lines.append(f"Day {as_int(payload.get('day'))} after the outbreak, {clip(payload.get('clock'), 5)}.")
    lines.append(f"Where: {format_place(payload.get('place'), code)}")
    weather = as_dict(payload.get("weather"))
    sky = [w for w, key in (("rain", "raining"), ("snow", "snowing"), ("thunder", "thunder")) if weather.get(key)]
    if sky:
        lines.append("Weather: " + ", ".join(sky))
    radio = format_radio(payload.get("radio"), code, "one of them")
    if radio:
        lines.append("Recent radio talk they know about:")
        lines.extend(radio)
    said = [clip(x, 160) for x in as_list(payload.get("said"))[-MAX_SAID:] if x]
    if said:
        lines.append("Lines they said recently (do not repeat): " + " / ".join(said))
    lines.append("What just happened: " + format_banter_event(payload.get("event"), code))
    lines.append(f"Write 2 to {MAX_BANTER_LINES} lines between: {', '.join(names)}.")
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"speaker": {"type": "string", "enum": names}, "text": {"type": "string"}},
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["lines"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="banter",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("banter"),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 2000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


BUILDERS = {
    "debug": build_debug,
    "journal": build_journal,
    "banter": build_banter,
    "radio_scene": build_radio_scene,
    "director": build_director,
    "radio": build_radio,
    "monologue": build_monologue,
    "summary": build_summary,
}


def build_request(module: str, payload: dict, mcfg: dict) -> LLMRequest:
    builder = BUILDERS.get(module)
    if builder is None:
        raise ModuleError("unknown_module")
    if not isinstance(payload, dict):
        raise ModuleError("bad_payload")
    return builder(payload, mcfg)
