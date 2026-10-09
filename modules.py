"""게임 요청(module + payload)을 LLM 요청으로 바꾼다.

각 모듈의 프롬프트 조립은 여기서만 한다. 게임 쪽 payload 는 신뢰하지 않는 입력으로 보고
타입을 확인하고 길이를 자른 뒤 사용한다. Lua 는 구조화된 사실만 보내고, 문장은 여기서 만든다.
"""

from __future__ import annotations

import contextvars
import re
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
    "world_power": "the power grid went down across the county; the lights and fridges died for good",
    "world_water": "the water stopped running from the taps",
    "world_winter": "winter set in and the nights turned freezing",
    "world_snow": "the first snow of the winter fell",
    "world_day30": "it has been a month since the outbreak",
    "world_day90": "it has been three months since the outbreak",
    "world_day180": "it has been half a year since the outbreak",
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
    "donation": "sent supplies over to {who} to help their people ({item})",
    # 2차 특기 (모드 Specialty2.lua, 2026-10-09)
    "specialty2_livestock": "{who} and the neighbors brought them some farm animals",
    "specialty2_stew": "{who} sent them a pot of home-cooked stew",
    "specialty2_praise": "{who} promised to praise them on the evening radio broadcast",
    "specialty2_sos": "they hit the SOS beacon and {who} rallied the radio contacts to help them at once",
    "specialty2_power": "{who} patched the dead power grid back on for a few days",
    "specialty2_illness": "{who} talked them through curing their sickness",
    "specialty2_pain": "{who} set them up with a pain regimen for a few days",
    "specialty2_pharmacy": "{who} turned the herbs they sent into medicine",
    "specialty2_reconcile": "{who} made peace between them and someone who had stopped trusting them",
    "specialty2_baptism": "{who} baptized them over the radio",
    "specialty2_tuning": "{who} talked them through tuning their vehicle's engine",
    "specialty2_bodyguard": "{who} put a couple of their people on them as bodyguards",
    "specialty2_game": "{who} shared meat from a hunt with them",
    "specialty2_rain": "{who} and the neighbors prayed for rain, and rain was promised for the next morning",
    "specialty2_refugees": "{who} sent refugees to clear the bodies around their home",
    "specialty2_tow": "{who} sent a tow truck for their stranded car",
    "specialty2_reinforce": "{who} talked them through bracing their vehicle to plough through the dead",
    "specialty2_artillery": "{who} called in an artillery strike on a spot they marked",
    "specialty2_evac": "{who} sent a helicopter to fly them home",
    "specialty2_barricade": "{who} had engineers bolt metal sheets over {count} windows at their home",
    "specialty2_heist": "{who} sent the crew to clean out a building they marked",
    "specialty2_camo": "{who} showed them how to smear themselves with zombie guts so the dead would leave them alone",
    "specialty2_suppressor": "{who} rigged suppressors on their guns for a day",
    "specialty2_flare": "{who} lit emergency flares around them",
    "specialty_guard": "{who} sent a squad of soldiers to back them up",
    "specialty_snipe_start": "{who} started covering them with a rifle from far away",
    "specialty_snipe": "{who} shot {count} of the dead around them from a distance",
    "specialty_doc": "{who} talked them through treating {count} injuries over the radio",
    "specialty_dewey": "{who} said they were on the way to repair their vehicle",
    "specialty_dewey_done": "{who} came by and repaired their vehicle",
    "specialty_casey": "{who} scouted the area and marked the dangers on their map",
    "specialty_ray": "{who} drove supplies over to {item} on their behalf",
    "specialty_pike": "{who} prayed with them over the radio and calmed their fear",
    "specialty_rats": "{who} made a racket far away to pull the dead off them",
    "npc_dead": "heard over the radio that {who} had died",
    "project_donation": "sent supplies to help {who} with their big project ({item})",
    "project_done": "heard that {who} finished their big project ({item}) with the players' help",
    "npc_gone": "{who} left for good and went off the air",
    "named_accepted": "agreed to find and put to rest someone {who} once knew, who had turned",
    "named_declined": "turned down {who}'s request to put a turned friend of theirs to rest",
    "named_completed": "{by} put to rest someone {who} once knew, who had turned, and brought back what they carried",
    "named_failed": "never found the turned friend {who} had asked them to put to rest",
    "recover_found": "found what {by}, the survivor who came before them, left behind where they fell",
    "memorial_read": "read the last diary pages of {by}, who died before them",
    # 이전 버전 세이브 호환
    "supply_offered": "heard that someone left supplies at {place}",
    "supply_approached": "got close to the building where the supplies were left ({place})",
    "supply_entered": "went into the building where the supplies were left ({place})",
    "supply_looted": "{by} found the supplies at {place}",
    "supply_expired": "never went for the supplies at {place}",
}


HOLIDAY_NAMES = {
    "newyear": "New Year's Day", "seollal": "Seollal (the Korean Lunar New Year)",
    "daeboreum": "Jeongwol Daeboreum (the first full moon of the lunar year)", "dano": "Dano (a Korean early-summer festival)",
    "chuseok": "Chuseok (the Korean harvest festival)", "dongji": "Dongji (the Korean winter solstice)",
    "christmas": "Christmas", "july4": "the Fourth of July", "halloween": "Halloween", "thanksgiving": "Thanksgiving",
}


def faction_label(fid: Any, lang: Any, voice: Any = None) -> str:
    """voice: 그 줄을 말한 사람 (게임이 줄마다 남김). False = 처음 사람, 후임 id, None = 지금 사람 (예전 기록)."""
    if voice is False:
        faction = FACTIONS.get(str(fid))
    elif isinstance(voice, str) and voice in VOICES and str(fid) in FACTIONS:
        faction = dict(FACTIONS[str(fid)])
        faction.update(VOICES[voice])
    else:
        faction = PERSONAS.get(str(fid))
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
        who = faction_label(m.get("faction"), lang, m.get("voice")) or (
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
    if kind == "letter_read":
        writer = faction_label(note.get("faction"), lang) or "someone"
        text = f"{clip(note.get('clock'), 5)} read a handwritten letter from {writer} that came with some supplies"
        body = clip(note.get("text"), 300)
        return text + (f': "{body}"' if body else "")
    if kind == "broadcast_heard":
        heard = [clip(line, 200) for line in as_list(note.get("lines"))[:4] if line]
        host = faction_label(note.get("faction"), lang) or "someone"
        text = f"{clip(note.get('clock'), 5)} listened to {host}'s evening news on the radio"
        return text + (": " + " / ".join(f'"{x}"' for x in heard) if heard else "")
    if kind == "holiday":
        # 명절 (게임 Holiday.lua): 한국어 게임이면 한국 명절, 아니면 미국 명절
        name = HOLIDAY_NAMES.get(str(note.get("holiday")), "a holiday")
        host = faction_label(note.get("faction"), lang)
        text = f"{clip(note.get('clock'), 5)} it was {name}; everyone on the radio celebrated together"
        if host:
            text += f", led by {host}"
        if note.get("full"):
            text += ", with a real holiday meal made from what the survivors gathered"
        return text
    if kind == "op":
        # 복구 작전 소식 (게임이 영어 문장을 만들어 보낸다, Ops.lua)
        text = clip(note.get("text"), 400)
        return f"{clip(note.get('clock'), 5)} {text}".strip() if text else None
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
    "npc_emergency": "A radio contact whose people have almost run out of something vital (see the contacts' "
                     "situation) urgently asks the target for exactly that, with only one day to deliver once they agree. "
                     "Same trust rules as npc_request. Strongly consider it when a contact is running out; it shows the "
                     "world reacting to their hardship.",
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
    world = [clip(x, 40) for x in as_list(payload.get("world"))[:4] if x]
    if world:
        lines.append("County conditions now: " + ", ".join(world) + ".")
    npcs = [as_dict(n) for n in as_list(payload.get("npcs"))]
    if npcs:
        lines.append("Radio contacts' situation (their people's supplies, 0-100):")
        for n in npcs:
            f = PERSONAS.get(str(n.get("id")))
            if not f:
                continue
            lines.append(f"- {f['name']} (trust {as_int(n.get('trust'))}): {life_state_words(n.get('state'))}")
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
        "who": "A sixteen-year-old girl, a ham radio operator broadcasting from her father's radio shack in Valley Station, "
               "north of West Point. Her father is sick in bed. Bright, nervous, talks fast, loves electronics and "
               "radio jargon, and is desperate for someone to talk to. Knows batteries, radios, generators and wiring. "
               "Tries to sound older than she is. Reads a short evening news broadcast at 19:00 on 105.4 MHz "
               "(\"Valley Station Evening News\"), replayed at 07:00, for anyone with a radio.",
        "trust": "Starts eager and friendly, but gets scared and closes up if anyone sounds threatening.",
        "speech": {"KO": "polite 해요체 toward adults, a bit breathless (~요, ~거든요, ~잖아요). Never banmal."},
        "trade_tiers": {
            "tools": ["batteries, wire, a flashlight or a pager", "a radio, walkie-talkie or small electronics",
                      "a better radio, a scanner or a lantern", "an amplifier, an old generator or a motion sensor",
                      "a generator or a military radio"],
        },
    },
    "doc": {
        "name": "June Adler",
        "local": {"KO": "준 애들러"},
        "who": "A former ER nurse in her forties who keeps a small clinic running in Riverside, caring for a handful "
               "of wounded survivors. Calm, direct, exhausted, dry sense of humour. Rations medicine carefully and "
               "asks one or two sharp questions about an injury, then gives practical advice. Will not waste supplies on people who lie to her.",
        "trust": "Starts polite but guarded. Warms to people who are honest and look after others.",
        "speech": {"KO": "calm, polite 존댓말 (합쇼체 and 해요체: ~습니다, ~세요, ~해요). Colder or warmer with trust, but never banmal."},
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
        "who": "A woman mechanic in her thirties living in her garage in Echo Creek, surrounded by half-fixed cars. "
               "Friendly in a gruff way, loves talking about engines when it comes up, swears when things go wrong. Trades car parts "
               "and tools and dreams of building a truck that can get people out of the county.",
        "trust": "Starts neutral. Likes people who keep their word and can fix things.",
        "speech": {"KO": "gruff, friendly, tomboyish banmal (~야, ~지, ~거든, ~냐). She is a woman: never call yourself 형/아저씨 or use masculine self-references."},
        "trade_tiers": {
            "tools": ["a tire pump, jack, lug wrench or spare engine parts", "brakes, a muffler or suspension parts",
                      "better suspension, brakes or tires", "a car battery, a windshield or a beacon light",
                      "a jerry can, a car battery or rare parts"],
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
    },
}


# 후임 목소리 (모드 Voices.lua, 2026-10-07): 앞 사람이 죽거나 떠난 뒤 같은 주파수를 이어받은 사람.
# 게임이 요청마다 payload.voices = { 채널: 후임 } 을 붙이면, 그 채널의 이름·성격·말투를 이 사전으로 바꾼다
# (거래 등급 설명 같은 거점 정보는 그대로).
VOICES = {
    "martha": {
        "name": "Martha Cole",
        "local": {"KO": "마사 콜"},
        "who": "A widow in her sixties from the farm next to Ray Mercer's outside West Point. She had promised to watch "
               "Ray's farm; now she runs it and keeps his radio and notebook of frequencies. Blunt, generous, "
               "unsentimental, practical about everything.",
        "trust": "Starts as a stranger who heard about the players from Ray.",
        "speech": {"KO": "blunt banmal of an older country woman (~지, ~어, ~다, sometimes ~구먼). Never 존댓말, never 하게체."},
    },
    "nora": {
        "name": "Nora Bell",
        "local": {"KO": "노라 벨"},
        "who": "A radio operator in her twenties from Brandenburg who used to listen to Casey Liu's broadcasts and came "
               "down to keep Casey's frequency in Valley Station alive. Calm, wry, organized; learning the county from "
               "Casey's logbook.",
        "trust": "Starts as a stranger who knows the players only from Casey's logbook.",
        "speech": {"KO": "calm, polite 해요체 (~요). Never banmal."},
    },
    "sam": {
        "name": "Sam",
        "local": {"KO": "샘"},
        "who": "The boy whose broken leg June Adler set, seventeen now and her apprentice, running the Riverside clinic "
               "with her notes and kit. Earnest, nervous, learning fast, scared of getting it wrong.",
        "trust": "Starts as a stranger who knows the players helped June.",
        "speech": {"KO": "nervous, polite 해요체 (~요), 습니다 when serious. Never banmal."},
    },
    "esther": {
        "name": "Esther Gray",
        "local": {"KO": "에스더 그레이"},
        "who": "The woman in her fifties who ran the kitchen and storeroom of the March Ridge church. Not a preacher; "
               "she keeps the place running and the doors open. Practical, warm, no patience for nonsense.",
        "trust": "Starts as a stranger who heard about the players from Brother Pike.",
        "speech": {"KO": "warm, motherly 해요체 with ~지요 (~요, ~지요). Never banmal."},
    },
    "lenny": {
        "name": "Lenny Austin",
        "local": {"KO": "레니 오스틴"},
        "who": "A young man Dewey Hollis was teaching to be a mechanic, now running her Echo Creek garage. Eager, "
               "clumsy, worshipped Dewey, talks to her tools when nobody is listening.",
        "trust": "Starts as a stranger who heard about the players from Dewey.",
        "speech": {"KO": "eager, casual banmal (~야, ~거든, ~냐)."},
    },
    "kowalski": {
        "name": "Corporal Kowalski",
        "local": {"KO": "코왈스키 상병"},
        "who": "The last corporal of Sergeant Whitaker's National Guard squad, twenty-two, suddenly in command at the "
               "Knox Boundary Camp. Tries to sound like Whitaker and fails; careful with ammunition.",
        "trust": "Starts wary, like Whitaker, but less sure of himself.",
        "speech": {"KO": "stiff military 다나까 speech (~다, ~습니다, ~나?), sometimes faltering. Never 해요체, never casual banmal."},
    },
    "red": {
        "name": "Red",
        "local": {"KO": "레드"},
        "who": "A sharp-tongued woman who stayed with the Coalfield crew after the raid and holds it together now. "
               "Pragmatic, tired of fighting, wants fewer fights and more deals.",
        "trust": "Starts cold but fair.",
        "speech": {"KO": "dry, sharp banmal (~야, ~지, ~거든)."},
    },
    "dutch": {
        "name": "Dutch",
        "local": {"KO": "더치"},
        "who": "Vic's former second, now running the Coalfield crew like a warlord. Menacing, greedy, enjoys threats and "
               "making people pay; will still trade if the price is right.",
        "trust": "Starts hostile. Respects only strength and payment.",
        "speech": {"KO": "menacing, mocking banmal (~냐, ~지, ~해라)."},
    },
    "caleb": {
        "name": "Caleb Tate",
        "local": {"KO": "케일럽 테이트"},
        "who": "The son of Hank Tolliver's late hunting partner Earl, in his thirties, a carpenter. Came looking for "
               "Hank, found the Ekron cabin empty and stayed to keep the trap lines. Quiet like Hank, gentler.",
        "trust": "Starts as a quiet stranger.",
        "speech": {"KO": "quiet, plain 존댓말 (~습니다, ~요), few words."},
    },
}

_VOICES = contextvars.ContextVar("storyengine_voices", default={})


class _Personas:
    """FACTIONS 를 읽되, 이 요청에서 후임이 이어받은 채널은 후임의 이름·성격·말투로."""

    def get(self, fid, default=None):
        base = FACTIONS.get(fid)
        if base is None:
            return default
        voice = _VOICES.get().get(str(fid))
        if voice and voice in VOICES:
            merged = dict(base)
            merged.update(VOICES[voice])
            return merged
        return base

    def __getitem__(self, fid):
        value = self.get(fid)
        if value is None:
            raise KeyError(fid)
        return value

    def __contains__(self, fid):
        return fid in FACTIONS


PERSONAS = _Personas()
MAX_HISTORY = 16
TRADE_CATEGORIES = ["firearm", "ammo", "tools", "medical", "melee", "food"]
# counter / withdraw 는 답을 기다리는 제안을 흥정할 때만 쓴다
TRADE_ACTIONS = ["none", "offer", "refuse", "gift", "counter", "withdraw"]
# 등급별 거래 물건 안내 (게임 Trade.lua GOODS 와 맞춘다)
TRADE_TIERS = {
    # 2026-10-04 기준: 묶음의 첫 물건이 그 등급 물건이고 나머지는 더 작은 것들 (게임이 실시간으로 고른다)
    "food": ["snacks and small bites", "a few cans or snacks", "proper meals (cans, jerky) and snacks",
             "hearty food for several days", "a big stock of filling food"],
    "medical": ["bandages, plasters or wipes", "a bottle of pills (painkillers, antibiotics...) with dressings",
                "a wound-care tool (tweezers, suture needle, splint or scalpel) with pills and dressings",
                "several wound-care tools with medicine and dressings",
                "a large mix of wound-care tools, medicine and dressings"],
    "tools": ["a very common tool (hammer, saw, screwdriver)", "a common tool (hand axe, bolt cutters, file)",
              "a less common tool (chisels, club hammer, small saw)", "an uncommon tool (fire axe, wood axe, welding mask)",
              "a rare tool (sledgehammer, pickaxe, anvil)"],
    "melee": ["a weak or fragile weapon", "a light weapon", "a decent weapon", "a strong weapon",
              "a top weapon that hits hard and lasts"],
    "firearm": ["a light pistol or revolver (or a bolt-action small-caliber rifle) with ammo",
                "a magnum handgun or a manual-action rifle with ammo",
                "an intermediate-caliber semi-auto rifle or a submachine gun with ammo",
                "a pump shotgun or a full-power semi-auto rifle with ammo",
                "an automatic rifle or heavy-caliber weapon with ammo"],
    "ammo": ["a box of pistol ammo (.38, 9mm, .45)", "magnum ammo (.357, .44)", "intermediate rifle ammo (5.56, 5.45, 5.8)",
             "full-power ammo (.308, .30-30, 12 gauge)", ".338 magnum rifle ammo"],
}


def tier_name(fid: str, cat: str, tier: int) -> str:
    names = PERSONAS.get(fid, {}).get("trade_tiers", {}).get(cat, TRADE_TIERS.get(cat, []))
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
        "- Your words alone never change this deal. If you agree to change anything (price, payment or goods), put "
        "it in \"trade\" with action \"counter\"; if you do not, say plainly that the terms stay as they are.",
    ]
    # 흥정 중에 물건을 바꿔 줄 수 있는 품목·등급 (게임이 Trade.negotiate 에서 다시 검증하고 값을 새로 매긴다)
    swaps = []
    for g in as_list(trade.get("goods")):
        g = as_dict(g)
        gcat = str(g.get("category"))
        top = max(0, min(5, as_int(g.get("maxTier"))))
        if gcat in TRADE_TIERS and top > 0:
            swaps.append(f"{gcat} up to tier {top} ("
                         + "; ".join(f"{t} = {tier_name(fid, gcat, t)}" for t in range(1, top + 1)) + ")")
    if left > 0:
        lines += [
            f"- They may haggle: ask for a lower price, or offer to pay in another category you accept "
            f"({', '.join(wants) or pay}). Your lowest price is {floor} value points; the game never goes lower. "
            f"Haggling rounds left: {left}.",
            "- Decide in character how far you move: take their price if it is at or above your lowest, meet them "
            "halfway, or hold firm. Give ground step by step over the rounds; do not drop straight to your lowest "
            "price, least of all for an insulting offer. To change the terms use action \"counter\" with the new \"price\" and "
            "\"pay_category\" (keep the deal's category and tier unless you swap goods). To keep the terms use action \"none\".",
            "- While haggling you may say the price in your reply.",
        ]
        if swaps:
            lines += [
                "- If they want different goods instead, you may swap them: action \"counter\" with the new "
                "\"category\" and \"tier\" (the game rolls the new goods and sets a fresh price, so put \"price\" 0). "
                "You can swap to: " + " | ".join(swaps) + ".",
                "- Anything not in that list you cannot give in this deal; say so instead of agreeing.",
                "- If they want one specific item instead, put its plain English name in \"item\" and their words in "
                "\"item_said\" (with action \"counter\"); the game swaps in a bundle with it if you carry it. Otherwise "
                "leave both empty.",
            ]
        else:
            lines.append("- You have nothing else to swap in right now. If they want different goods, say so; the "
                         "goods stay the same.")
    else:
        lines.append("- No more haggling: you have moved as far as you will. Keep the terms (action \"none\"), "
                     "or call off the deal (action \"withdraw\") if they keep pushing.")
    lines.append("- If their offer is insulting (far below your lowest price) or they are rude about it, you may lower "
                 "trust by 1 and you may call off the deal with action \"withdraw\".")
    return lines


def format_trade_rules(trade: dict, fid: str = "") -> list[str]:
    trade = as_dict(trade)
    special = PERSONAS.get(fid, {}).get("trade_tiers", {})
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
    empty, short = [], []
    for c in as_list(trade.get("catalog")):
        c = as_dict(c)
        cat = str(c.get("category"))
        if cat in TRADE_TIERS:
            catalog.append((cat, max(0, as_int(c.get("maxTier"))), [as_int(n, 101) for n in as_list(c.get("needs"))]))
            if c.get("empty"):
                empty.append(cat)
            elif c.get("short"):
                short.append(cat)
    if catalog:
        # 취급하는 모든 등급을 보여 주고, 아직 못 주는 등급은 필요한 신뢰도와 함께 잠김으로 표시한다
        for cat, top, needs in catalog:
            names = special.get(cat, TRADE_TIERS[cat])
            if cat in empty:
                lines.append(f"  {cat}: none to spare right now, your own people are out of it")
                continue
            tiers = []
            for i, need in enumerate(needs[:len(names)]):
                if i + 1 <= top:
                    tiers.append(f"{i + 1} = {names[i]}")
                elif need <= 100:
                    tiers.append(f"{i + 1} = {names[i]} (locked: needs trust {need})")
            lines.append(f"  {cat}: " + "; ".join(tiers))
        if empty:
            lines.append("- If they ask for " + " or ".join(empty) + ", refuse (action \"refuse\") and say your own "
                         "people are out of it; it has nothing to do with trust.")
        if short:
            lines.append("- You are short on " + ", ".join(short) + " yourself, so those cost more than usual "
                         "(the game already raised the price).")
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
    lines.append("- The game picks the exact goods: the first item is of the tier, the rest is smaller stuff. If the player asked for one specific item (\"tweezers\", \"a hunting rifle\"), put its plain English item name in \"item\" and the words they used in \"item_said\"; the game puts that item in the deal if you carry it at a tier you can offer now, otherwise no offer is made and they are told you do not have it. Never promise a specific item unless you set \"item\"; otherwise leave both empty and talk about the kind of goods, not exact items.")
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
# NPC 사이 관계 값(-3..3, 게임 Bonds.lua)을 말로. 관계표 메모는 처음 사이라 지금 마음이 우선
BOND_WORDS = {
    -3: "you can't stand them",
    -2: "you dislike them",
    -1: "you are wary of them",
    0: "neither warm nor cold",
    1: "you get along",
    2: "you like them",
    3: "they are a close friend",
}


def bond_line(o, subject="you"):
    """관계 값·최근 변화 문구. subject 가 you 가 아니면 3인칭으로."""
    parts = []
    if o.get("bond") is not None:
        b = max(-3, min(3, as_int(o.get("bond"), 0)))
        word = BOND_WORDS[b]
        if subject != "you":
            word = (word.replace("you can't", "they can't").replace("you dislike", "they dislike")
                    .replace("you are", "they are").replace("you get", "they get").replace("you like", "they like")
                    .replace("they are a close friend", "a close friend"))
        parts.append(f"feeling now: {word}")
    shift = clip(o.get("shift"), 200)
    if shift:
        parts.append(f"what changed it lately: {shift}")
    return "; ".join(parts)


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
        f = PERSONAS.get(str(o.get("id")))
        note = clip(o.get("note"), 200)
        bond = bond_line(o)
        if not f or not (note or o.get("shift") or as_int(o.get("bond"), 0) != 0):
            continue
        gone = str(o.get("gone") or "")
        if gone in ("dead", "gone"):
            # 죽었거나 떠난 사람: 지금 형편이나 신뢰도 대신 그 사실만
            what = "died recently" if gone == "dead" else "left the county and is no longer on the radio"
            others.append(f"- {f['name']}: {note or 'someone you knew on the radio'}; {f['name']} {what}. "
                          "You still think about them.")
            continue
        line = f"{f['name']}: {note or 'you did not know them well at first'}"
        if bond:
            line += f"; {bond}"
        trust = as_int(o.get("trust"), -1)
        if trust >= 0:
            line += f"; how much they (not you) trust the players: {trust_word(trust)}"
        obeat = clip(o.get("beat"), 220)
        if obeat:
            line += f'; their situation lately, in their own words ("you" means them): {obeat}'
        others.append("- " + line)
    if others:
        out.append("Other people on the radio you know (mention them when it comes up naturally; "
                   "if your feeling now differs from how things started, the feeling now is what counts):")
        out.extend(others)
    news = [clip(x, 300) for x in as_list(story.get("news"))[-3:] if x]
    if news:
        out.append("Things you have heard lately: " + " ".join(news))
    return out


# 게임 Life.context: 이 NPC 무리의 형편(생활 자원), 플레이어들과 있었던 일, 평판
LIFE_RESOURCES = [("food", "food and water"), ("medical", "medicine"), ("safety", "ammunition and defenses"),
                  ("morale", "morale")]


def life_level(v: int) -> str:
    if v < 20:
        return "none left" if v < 10 else "almost gone"
    if v < 40:
        return "running low"
    if v < 70:
        return "enough for now"
    return "plenty"


RECORD_TEXT = {
    "player_died": "you heard that {who} died",
    "quest_completed": "{who} did what you asked",
    "quest_failed": "{who} promised to help and never did",
    "quest_declined": "{who} turned down your request",
    "quest_ignored": "nobody answered your request",
    "quest_accepted": "{who} agreed to help you",
    "trade_done": "{who} completed a trade with you",
    "trade_failed": "{who} backed out of a trade with you",
    "crisis_helped": "{who} chose to help you when several people needed help",
    "crisis_ally": "{who} helped someone else in a crisis in a way that also helped your people",
    "crisis_snubbed": "{who} chose to help someone else instead of you in a crisis",
    "crisis_ignored": "nobody answered when you asked for help in a crisis",
    "donation": "{who} sent your people supplies without being asked",
    "insult": "{who} was rude to you on the radio",
    "spill_up": "{who} helped {src}, whom you like",
    "spill_down": "{who} helped {src}, whom you do not like",
    "rescued": "you sent armed people to back {who} up when they were in danger",
    "specialty": "you used your special skills to help {who}",
    "ray_supply": "{who} had the West Point farm bring your people supplies",
    "survived": "you came close to the end and barely survived",
    "project_gift": "{who} sent supplies for your big project",
    "project_done": "you finished your big project with the players' help",
    "operation_done": "the players got the county's power or running water working again",
    "saga_saved": "the players helped your people get through a disaster that hit the county",
}
TAG_TEXT = {
    "reliable": "someone you can count on",
    "healer": "the one who brings medicine",
    "abandoner": "the ones who left you when it mattered",
    "unreliable": "someone who does not keep promises",
    "generous": "generous",
    "vic_friend": "someone who runs with the Coalfield crew",
}


def life_state_words(state: Any) -> str:
    state = as_dict(state)
    parts = []
    for key, word in LIFE_RESOURCES:
        if key in state:
            v = max(0, min(100, as_int(state.get(key))))
            parts.append(f"{word} {life_level(v)} ({v}/100)")
    return ", ".join(parts)


def format_newcomer(info: Any) -> list[str]:
    """이 NPC 에게 처음 말을 거는 캐릭터 (Legacy.lua): 함께 다니는 사람들, 최근 이 무리에서 죽은 사람."""
    info = as_dict(info)
    name = clip(info.get("name"), NAME_LIMIT)
    if not name:
        return []
    out = [f"{name} is a voice you have never heard before on this channel. The trust you have is with the players' "
           "group as a whole, so treat them as part of it, but notice that they are new to you."]
    companions = [clip(c, NAME_LIMIT) for c in as_list(info.get("companions"))[:3] if c]
    if companions:
        out.append(f"{name} travels with the same group as " + ", ".join(companions) + ".")
    dead = []
    for d in as_list(info.get("dead"))[:3]:
        d = as_dict(d)
        who = clip(d.get("name"), NAME_LIMIT)
        if not who:
            continue
        ago = as_int(d.get("daysAgo"))
        when = "today" if ago <= 0 else ("yesterday" if ago == 1 else f"{ago} days ago")
        line = f"{who} died {when}"
        what = clip(d.get("what"), 300)
        if d.get("knew") and what:
            line += f" (between {who} and you: {what})"
        elif not d.get("knew"):
            line += " (you never really dealt with them)"
        dead.append(line)
    if dead:
        out.append("The group lost people recently: " + "; ".join(dead) + ". You may wonder aloud whether this new voice "
                   "knew them or is taking their place, if it fits naturally. Do not invent how they died.")
    return out


def format_life_context(life: Any) -> list[str]:
    life = as_dict(life)
    out = []
    words = life_state_words(life.get("state"))
    if words:
        out.append(f"How your people are doing right now: {words}. Let this show in how you sound and what you "
                   "worry about, without reciting numbers.")
    records = []
    for r in as_list(life.get("records"))[-6:]:
        r = as_dict(r)
        template = RECORD_TEXT.get(str(r.get("kind")))
        if not template:
            continue
        src = PERSONAS.get(str(r.get("src")), {}).get("name", "someone")
        line = template.format(who=clip(r.get("who"), NAME_LIMIT) or "one of them", src=src)
        if r.get("dead") and r.get("kind") != "player_died":
            line += f" ({clip(r.get('who'), NAME_LIMIT)} is dead now)"
        d = as_int(r.get("d"))
        records.append(f"- day {as_int(r.get('day'))}: {line}" + (f" (trust {d:+d})" if d else ""))
    if records:
        out.append("What has happened between you and these players (oldest first; bring it up when it fits, "
                   "you remember it):")
        out.extend(records)
    project = as_dict(life.get("project"))
    pname = clip(project.get("name"), 120)
    if pname:
        if project.get("done"):
            out.append(f"Your big project, {pname}, is finished thanks to the players. You are proud of it.")
        else:
            goal = as_int(project.get("goal"), 100) or 100
            pct = as_int(project.get("percent"), -1)
            if pct < 0:
                pct = as_int(project.get("points")) * 100 // goal
            pct = max(0, min(100, pct))
            out.append(f"Your big project: {pname}, about {pct}% done"
                       + (" (the players have been helping)." if pct > 0 else " (not started yet)."))
    tags = [TAG_TEXT[t] for t in as_list(life.get("tags")) if t in TAG_TEXT]
    if tags:
        out.append("How you think of them by now: " + "; ".join(tags) + ".")
    return out


FOLLOW_UP_HOURS = [0, 1, 2, 3, 4, 6, 8, 12, 24]
MAX_MESSAGE = 240


# NPC 특기 (게임 Specialty.lua): 플레이어가 거점 탭의 특기 버튼으로 청한다. AI 는 알려 주기만 한다
SPECIALTY = {
    "guard": "send an armed squad (or a marksman) to back them up for a few hours",
    "doc": "talk them through treating their worst injury over the radio (first aid; it cannot cure a bite)",
    "dewey": "come out and repair their vehicle",
    "casey": "scout the area with your radio gear and mark the dangers on their map",
    "ray": "drive a load of supplies over to another survivor group on their behalf",
    "pike": "comfort them over the radio (a prayer, or simply a kind voice) and calm their fear and nerves",
    "hunter": "cover them with your rifle from a distance and shoot the dead around them",
    "rats": "make a racket far away to pull the dead off them",
}
SPECIALTY_REASON = {
    "low_trust": "not yet: you do not trust them enough (needs trust 40)",
    "cooldown": "not right now: you did it recently, wait about {wait} more hours",
    "no_resource": "not right now: your own people are too short of supplies",
    "ill": "not right now: you are sick",
    "gone": "no",
    "off": "no",
}


# 게임 화면의 이름 (모드 번역 파일과 같게): 거점 탭, 특기 버튼
SPECIALTY_UI = {"KO": ("거점", "특기"), "EN": ("Bases", "Specialty")}


def format_specialty(fid: str, status: Any, code: str = "EN") -> str | None:
    what = SPECIALTY.get(fid)
    status = as_dict(status)
    if not what or not status:
        return None
    reason = str(status.get("reason") or "")
    if reason in ("gone", "off"):
        return None
    if reason:
        now = SPECIALTY_REASON.get(reason, "not right now").format(wait=as_int(status.get("wait")))
    else:
        now = "yes, you can do it now"
    tab, button = SPECIALTY_UI.get(code, SPECIALTY_UI["EN"])
    return (f"What you can do for them (your special skill): {what}. They ask for it with the \"{button}\" button on "
            f"your page in their \"{tab}\" tab (use exactly these names). Can you right now: {now}.")


def format_player_state(name: str, state: Any) -> str | None:
    state = as_dict(state)
    if not state:
        return None
    hp = as_int(state.get("hp"), -1)
    wounds = []
    for w in as_list(state.get("wounds"))[:8]:
        w = as_dict(w)
        part = BODY_PARTS.get(str(w.get("part")), clip(w.get("part"), 30))
        kind = WOUNDS.get(str(w.get("kind")), clip(w.get("kind"), 20))
        extra = []
        if w.get("bleeding"):
            extra.append("bleeding")
        if w.get("bandaged"):
            extra.append("bandaged")
        wounds.append(f"{kind} on the {part}" + (f" ({', '.join(extra)})" if extra else ""))
    if hp < 0 and not wounds:
        return None
    health = ("unhurt" if hp >= 90 and not wounds else "lightly hurt" if hp >= 70
              else "hurt" if hp >= 45 else "badly hurt")
    text = f"How {name} is right now (facts; treat them as what they told you or what you can hear in their voice, "            f"and do not ask about them again): {health}"
    if wounds:
        text += "; " + "; ".join(wounds)
    return text + "."


# 개인 신뢰 (멀티 개인 모드, 2026-10-09): 이 사람을 얼마나 아는가
KNOWN_TEXT = {
    "well": "you know them well; you have dealt with them a lot",
    "little": "you have dealt with them a little",
    "new": "you barely know them yet",
}


def format_personal(value: Any, group: int) -> list[str]:
    """`personal = {name, trust, known}`: 집단 신뢰와 따로, 지금 말하는(또는 일의 대상인) 이 사람에 대한 태도."""
    p = as_dict(value)
    if not p:
        return []
    name = clip(p.get("name"), NAME_LIMIT) or "this person"
    trust = max(0, min(100, as_int(p.get("trust"), group)))
    known = str(p.get("known") or "")
    lines = [f"The person this call is about: {name}. Your own trust in {name} personally: {trust}/100."]
    if known in KNOWN_TEXT:
        lines.append(f"How well you know {name}: {KNOWN_TEXT[known]}.")
    lines.append(f"Your attitude toward {name} personally: {trust_tone(trust)}")
    lines.append(
        f"Two attitudes: the group one is how you feel about the players in general; the personal one decides how warm "
        f"and open you are with {name} in this call, and it also follows its number only. If you trust the group but "
        f"barely know {name}, be polite but careful with them. If {name} personally earned more trust than the group, "
        f"be warmer with them than with the group, even if the group trust is low. If you refuse a trade or hold "
        f"something back because of trust, put it as not knowing {name} well enough yet.")
    return lines


def build_radio(payload: dict, mcfg: dict) -> LLMRequest:
    fid = str(payload.get("faction", ""))
    faction = PERSONAS.get(fid)
    if not faction:
        raise ModuleError("unknown_faction")
    code = str(payload.get("lang") or "EN").upper()
    local_name = faction["local"].get(code, "")
    name = f"{faction['name']} ({local_name})" if local_name else faction["name"]

    trust = max(0, min(100, as_int(payload.get("trust"), 50)))
    persona = [
        f"You are: {name}. {faction['who']}",
        f"How you treat strangers at first (only matters before trust is built): {faction['trust']}",
    ]
    personal = format_personal(payload.get("personal"), trust)
    if personal:
        persona.append(f"Current trust in the players as a group: {trust}/100.")
        persona.append(f"Your attitude toward the players as a group right now: {trust_tone(trust)} This follows the "
                       "group trust number only; do not drift warmer or colder than this because of the log, your "
                       "memories or other people's feelings. Keep your own personality; the attitude changes how much "
                       "warmth and openness you show, not who you are.")
        persona.extend(personal)
    else:
        persona.append(f"Current trust in these players: {trust}/100.")
        persona.append(f"Your attitude toward them right now: {trust_tone(trust)} This follows the trust number only; "
                       "do not drift warmer or colder than this because of the log, your memories or other people's "
                       "feelings. Keep your own personality; the attitude changes how much warmth and openness you "
                       "show, not who you are.")
    speech = faction.get("speech", {}).get(code)
    if speech:
        persona.append(f"Your speech level in {language_name(code)}: {speech} Use this same speech level in every "
                       "message, whatever the trust and whatever earlier lines in the log used; trust changes warmth, "
                       "not speech level.")
    memory = clip(payload.get("memory"), 1000)
    if memory:
        persona.append(f"What you remember from earlier talks: {memory}")
    persona.extend(format_story_context(payload.get("story")))
    persona.extend(format_life_context(payload.get("life")))
    persona.extend(format_newcomer(payload.get("newcomer")))
    spec = format_specialty(fid, payload.get("specialty"), code)
    if spec:
        persona.append(spec)

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
        speaker = next((clip(as_dict(m).get("name"), NAME_LIMIT) for m in reversed(history)
                        if as_dict(m).get("from") == "player"), "") or "the player"
        state_line = format_player_state(speaker, payload.get("speakerState"))
        if state_line:
            lines.append(state_line)
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
                    "item": {"type": "string"},
                    "item_said": {"type": "string"},
                },
                "required": ["action", "category", "tier", "pay_category", "price", "item", "item_said"],
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
        faction = PERSONAS.get(str(payload.get("faction", "")))
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
REPLY_SCENE_LINES = 4      # 플레이어에게 답하는 장면 (2026-10-04: 줄 수를 채우려고 질문을 덧붙이지 않게)
SCENE_LOG = 20             # 장면에 보여 주는 최근 줄 (게임 Social.SCENE_LOG 와 같게)


MARKET_MAX = 3


def format_market(payload: dict, code: str, ids: list[str], lines: list[str]) -> tuple[list[str], list[str]]:
    """공용 주파수 거래: 플레이어가 물건을 청했을 때 제안할 수 있는 사람들. (제안할 수 있는 id, 말할 수 있는 id)"""
    market = as_dict(payload.get("market"))
    said = as_dict(payload.get("said"))
    speakers = list(ids)
    if not said.get("text") or not market:
        return [], speakers
    if market.get("closed"):
        why = {"open_deal": "they already have a trade going and must settle it first",
               "too_soon": "offers were made to them only a little while ago; tell them to settle on one or ask again later"}
        why = why.get(str(market.get("closed")), "nobody can spare anything right now")
        lines.append(f"Trading on this channel: if the player is asking for goods, nobody makes an offer now ({why}); "
                     "say so in character.")
        return [], speakers
    sellers = []
    top = max(1, min(MARKET_MAX, as_int(market.get("max"), MARKET_MAX)))
    lines.append(f"Trading on this channel (rules from the game): if the player is asking for goods or a trade, up to {top} "
                 "of the people below may each make one offer. Each offer is one category, at most the tier listed, and "
                 "asks for payment in one category that person accepts. Those who offer say so briefly in their own line "
                 "(plain words, no numbers; the exact goods and price are shown to the player). Choose who offers by what "
                 "the player asked for and how each person feels about the players. If the player is not asking for "
                 "goods, make no offers. The game picks the exact goods; if the player asked for one specific item, give "
                 "its plain English name in each offer's \"item\" and their words in \"item_said\" (offers from people "
                 "who do not carry it are dropped), otherwise leave both empty and never promise an exact item.")
    stock = {c: as_int(v) for c, v in as_dict(market.get("stock")).items() if c in TRADE_CATEGORIES and as_int(v) > 0}
    if stock:
        # 판매 시장: 플레이어가 가진 물건을 내놓으면 그것을 받는 사람들이 자기 물건을 제안한다 (게임이 값을 정한다)
        lines.append("What the player has to trade away (category: total value): "
                     + ", ".join(f"{c}: {v}" for c, v in stock.items()) + ".")
        lines.append("Selling: if the player is offering to sell or give up goods of one of those categories (\"anyone need "
                     "food?\", \"I have spare bandages\"), set \"selling\" to that category. Then only people who accept that "
                     "category make offers, every offer's pay_category is that category, and each offer is what that person "
                     "gives in return. People short of it are glad and pay more (the game sets the rate). If the player is "
                     "asking for goods rather than offering them, \"selling\" is \"none\".")
    lines.append("People who can trade now:")
    for x in as_list(market.get("sellers")):
        x = as_dict(x)
        fid = str(x.get("id"))
        if fid not in FACTIONS:
            continue
        goods = []
        for g in as_list(x.get("goods")):
            g = as_dict(g)
            cat = str(g.get("category"))
            t = max(0, min(5, as_int(g.get("maxTier"))))
            if cat in TRADE_TIERS and t > 0:
                goods.append(f"{cat} up to {t} ({tier_name(fid, cat, t)})")
        wants = [w for w in as_list(x.get("wants")) if w in TRADE_CATEGORIES]
        short = [w for w in as_list(x.get("short")) if w in wants]
        if not goods or not wants:
            continue
        sellers.append(fid)
        f = PERSONAS[fid]
        local = f["local"].get(code, "")
        name = f"{f['name']} ({local})" if local else f["name"]
        extra = ""
        if fid not in ids:
            # 장면 참가자가 아닌 사람은 제안할 때만 말한다
            speech = f.get("speech", {}).get(code)
            extra = (f" Not in the conversation so far: speaks only if they make an offer. {f['who']}"
                     + (f" Speech level, always the same: {speech}" if speech else "")
                     + f" Toward the players this person {trust_attitude(max(0, min(100, as_int(x.get('trust'), 30))))}.")
            speakers.append(fid)
        need = f" Short of {', '.join(short)} themselves." if short else ""
        lines.append(f"- {fid} = {name}: can offer {'; '.join(goods)}; accepts payment in {', '.join(wants)}.{need}{extra}")
    if not sellers:
        return [], list(ids)
    return sellers, speakers


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
        f = PERSONAS[fid]
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
        words = life_state_words(x.get("state"))
        if words:
            bits.append(f"Their people right now: {words}.")
        spec = format_specialty(fid, x.get("specialty"), code)
        if spec:
            bits.append(spec.replace("What you can do for them (your special skill)", "Their special skill")
                        .replace("your page", "their page").replace("Can you right now", "Can they right now")
                        .replace("you do not trust them", "they do not trust the players").replace("you did it", "they did it")
                        .replace("your own people", "their people").replace("you are sick", "they are sick")
                        .replace("yes, you can", "yes, they can"))
        rels = []
        for r in as_list(x.get("relations"))[:3]:
            r = as_dict(r)
            other = PERSONAS.get(str(r.get("id")))
            if not other:
                continue
            bits_r = [clip(r.get("note"), 200)] if r.get("note") else []
            bond = bond_line(r, subject="they")
            if bond:
                bits_r.append(bond)
            if bits_r:
                rels.append(f"about {other['name']}: " + ", ".join(bits_r))
        if rels:
            bits.append("What they think of the others here: " + "; ".join(rels) + ".")
        lines.append(" ".join(bits))
    players = [clip(pl, NAME_LIMIT) for pl in as_list(payload.get("players"))[:MAX_PLAYERS] if pl]
    if players:
        lines.append("Players listening: " + ", ".join(players))
    sellers, speakers = format_market(payload, code, ids, lines)
    lines.append("Recent talk on the open channel (oldest first):")
    log = as_list(payload.get("log"))[-SCENE_LOG:]
    for m in log:
        m = as_dict(m)
        text = clip(m.get("text"), MAX_MESSAGE)
        if not text:
            continue
        if m.get("from") == "player":
            who = f"{clip(m.get('name'), NAME_LIMIT) or 'a player'} (a player)"
        else:
            who = PERSONAS.get(str(m.get("npc")), {}).get("name", "someone")
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
        state_line = format_player_state(clip(said.get("name"), NAME_LIMIT) or "the player", said.get("state"))
        if state_line:
            lines.append(state_line)
        lines.append("Those who have something to add answer the player (usually one or two of them), then they may "
                     "react to each other. Do not repeat questions already asked or answered above.")
        count = f"Write 2 to {REPLY_SCENE_LINES} lines."
    else:
        lines.append(f"What they talk about now: {clip(payload.get('topic'), 400) or 'small talk'}")
        count = f"Write 3 to {MAX_SCENE_LINES} lines."
    lines.append(f"{count} Speak only {language_name(code)}. "
                 "Do not mix in English words, except radio words like \"over\" when natural.")
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"speaker": {"type": "string", "enum": speakers}, "text": {"type": "string"}},
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["lines"],
        "additionalProperties": False,
    }
    if sellers:
        # 공용 주파수 거래: 게임(Trade.marketOffers)이 신뢰도 한도·생활 자원으로 다시 검증하고 물건·값을 정한다
        schema["properties"]["offers"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "faction": {"type": "string", "enum": sellers},
                    "category": {"type": "string", "enum": TRADE_CATEGORIES},
                    "tier": {"type": "integer"},
                    "pay_category": {"type": "string", "enum": TRADE_CATEGORIES},
                    "item": {"type": "string"},
                    "item_said": {"type": "string"},
                },
                "required": ["faction", "category", "tier", "pay_category", "item", "item_said"],
                "additionalProperties": False,
            },
        }
        schema["properties"]["selling"] = {"type": "string", "enum": ["none"] + TRADE_CATEGORIES}
        schema["required"] = ["lines", "offers", "selling"]
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


# ---------------------------------------------------------------- broadcast

MAX_BROADCAST_LINES = 10
MAX_BROADCAST_FACTS = 12
BROADCAST_STATION = "Valley Station Evening News"


def build_broadcast(payload: dict, mcfg: dict) -> LLMRequest:
    """게임 속 라디오 저녁 방송 (Broadcast.lua). 진행자 한 명이 6~10줄."""
    code = str(payload.get("lang") or "EN").upper()
    host = str(payload.get("host"))
    f = PERSONAS.get(host)
    if not f:
        raise ModuleError("bad_payload")
    local = f["local"].get(code, "")
    name = f"{f['name']} ({local})" if local else f["name"]
    freq = clip(payload.get("freq"), 8) or "105.4"
    lines = [
        f"Language: {language_name(code)}",
        f'Station: "{BROADCAST_STATION}", {freq} MHz. Day {as_int(payload.get("day"))} after the outbreak, '
        f"{clip(payload.get('clock'), 5) or '19:00'}.",
        f"Host: {name}. {f['who']}",
    ]
    speech = f.get("speech", {}).get(code)
    if speech:
        lines.append(f"Host's speech level, always the same: {speech}")
    if host != "casey":
        lines.append("The usual host, Casey, is no longer on the air; this person keeps the broadcast going.")
    beat = clip(payload.get("beat"), 300)
    if beat:
        lines.append("What is going on in the host's own life (\"you\" means the host): " + beat)
    facts = [clip(x, 300) for x in as_list(payload.get("facts"))[:MAX_BROADCAST_FACTS] if x]
    if facts:
        lines.append("Today's news (facts, newest first):")
        lines.extend(f"- {x}" for x in facts)
    else:
        lines.append("Today's news: nothing new reached the host today.")
    conditions = [clip(x, 40) for x in as_list(payload.get("conditions"))[:4] if x]
    if conditions:
        lines.append("Life in the county now: " + ", ".join(conditions) + ".")
    weather = clip(payload.get("weather"), 200)
    lines.append(f"Weather forecast: {weather}" if weather else "Weather forecast: unknown, the host's barometer is acting up.")
    lines.append(f"Write 6 to {MAX_BROADCAST_LINES} lines and the rerun line. Speak only {language_name(code)}.")
    schema = {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"type": "string"}},
            "rerun": {"type": "string"},
        },
        "required": ["lines", "rerun"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="broadcast",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("broadcast"),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 4000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


# ---------------------------------------------------------------- letter

LETTER_REASONS = {
    "gift": "You are leaving a small package of supplies for them as a gift, and tucking this note inside.",
    "greenhouse": "Your greenhouse gave its first real harvest thanks to the players' help, and you are sending some of it "
                  "with this note.",
    "project": "Your big project ({extra}) is finally finished, and the players' help made it possible. You want to thank "
               "them properly, in writing.",
    "farewell": "You are leaving for good and will not be on the radio again ({extra}). This is your last letter to them, "
                "passed along with someone else's supplies.",
}


def build_letter(payload: dict, mcfg: dict) -> LLMRequest:
    """NPC 가 보급품에 넣는 손편지 (Letters.lua)."""
    code = str(payload.get("lang") or "EN").upper()
    fid = str(payload.get("faction"))
    f = PERSONAS.get(fid)
    reason = str(payload.get("reason"))
    if not f or reason not in LETTER_REASONS:
        raise ModuleError("bad_payload")
    local = f["local"].get(code, "")
    name = f"{f['name']} ({local})" if local else f["name"]
    lines = [
        f"Language: {language_name(code)}",
        f"Writer: {name}. {f['who']}",
    ]
    speech = f.get("speech", {}).get(code)
    if speech:
        lines.append(f"Writer's speech level, always the same, also in writing: {speech}")
    trust = max(0, min(100, as_int(payload.get("trust"), 50)))
    lines.append(f"Toward the players the writer {trust_attitude(trust)}.")
    memory = clip(payload.get("memory"), 1000)
    if memory:
        lines.append(f"What the writer remembers from radio talks with the players: {memory}")
    lines.extend(format_story_context(payload.get("story")))
    lines.extend(format_life_context(payload.get("life")))
    to = clip(payload.get("to"), NAME_LIMIT) or "the players"
    lines.append(f"Reader: {to}, one of the players.")
    lines.append("Why you are writing: " + LETTER_REASONS[reason].format(extra=clip(payload.get("extra"), 300) or "?"))
    lines.append(f"Write the letter now. Speak only {language_name(code)}.")
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
        "required": ["title", "text"],
        "additionalProperties": False,
    }
    return LLMRequest(
        module="letter",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("letter"),
        messages=[{"role": "user", "content": chr(10).join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 4000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


# ---------------------------------------------------------------- episode (AI 곁가지)

EPISODE_KINDS = {
    "quiet": "A quiet side story: something small happens in your life over a couple of days and then settles. "
             "No request to the players. Write \"start\" (it begins) and \"end\" (how it settled), and pick \"tone\".",
    "items": "A side story in which you ask the players for the items listed below. Write \"start\" (what happens and "
             "why you need those things, ending with the request), \"why\" (one short English clause for the quest log), "
             "\"win\" (how it turned out because they brought the items) and \"lose\" (how it turned out without them).",
    "horde": "A side story in which you ask the players to clear a group of the dead from a place near them (the game "
             "picks the place and tells them where). Write \"start\" (what happens and why the dead there are a "
             "problem for you, ending with the request), \"why\" (one short English clause for the quest log), \"win\" "
             "(how it turned out because they cleared it) and \"lose\" (how it turned out when nobody did).",
}


def item_words(full_type: Any) -> str:
    """"Base.TinnedBeans" -> "Tinned Beans" (AI 에 넘기는 물건 이름)."""
    name = str(full_type or "").split(".")[-1]
    name = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])", " ", name)
    return clip(name, 60)


def build_episode(payload: dict, mcfg: dict) -> LLMRequest:
    """AI 곁가지 (AiTales.lua): 게임이 종류·물건을 정하고 AI 는 짧은 이야기만 쓴다."""
    code = str(payload.get("lang") or "EN").upper()
    fid = str(payload.get("faction"))
    f = PERSONAS.get(fid)
    kind = str(payload.get("kind"))
    if not f or kind not in EPISODE_KINDS:
        raise ModuleError("bad_payload")
    local = f["local"].get(code, "")
    name = f"{f['name']} ({local})" if local else f["name"]
    lines = [
        f"Language for say, tale and title: {language_name(code)}",
        f"You are {name}. {f['who']}",
    ]
    speech = f.get("speech", {}).get(code)
    if speech:
        lines.append(f"Your speech level in \"say\", always the same: {speech}")
    trust = max(0, min(100, as_int(payload.get("trust"), 50)))
    lines.append(f"Toward the players you {trust_attitude(trust)}.")
    memory = clip(payload.get("memory"), 1000)
    if memory:
        lines.append(f"What you remember from radio talks with the players: {memory}")
    lines.extend(format_story_context(payload.get("story")))
    lines.extend(format_life_context(payload.get("life")))
    season = clip(payload.get("season"), 20)
    if season:
        lines.append(f"Season: {season}.")
    world = [clip(w, 40) for w in as_list(payload.get("world")) if w]
    if world:
        lines.append("County conditions now: " + ", ".join(world) + ".")
    players = [clip(p, NAME_LIMIT) for p in as_list(payload.get("players"))[:6] if p]
    if players:
        lines.append("Players on the radio now: " + ", ".join(players) + ".")
    recent = []
    for r in as_list(payload.get("recent"))[:12]:
        r = as_dict(r)
        bit = clip(r.get("title"), 80)
        beat = clip(r.get("beat"), 200)
        if bit or beat:
            recent.append("- " + (f"{bit}: " if bit else "") + (beat or ""))
    if recent:
        lines.append("Side stories you already had (do not repeat them, find something new):")
        lines.extend(recent)
    lines.append("")
    lines.append("What to write: " + EPISODE_KINDS[kind])
    if kind != "quiet":
        tier = max(1, min(5, as_int(payload.get("tier"), 1)))
        lines.append(f"Size of the request: {tier} of 5.")
        if kind == "items":
            wanted = []
            for it in as_list(payload.get("items"))[:6]:
                it = as_dict(it)
                n = max(1, as_int(it.get("count"), 1))
                wanted.append(f"{n} x {item_words(it.get('item'))}")
            if not wanted:
                raise ModuleError("bad_payload")
            lines.append("The items you ask for (exactly these): " + ", ".join(wanted) + ".")
        why = clip(payload.get("why"), 240)
        if why:
            lines.append(f"A reason the game had in mind (you may use it or write a better one that fits these items): {why}")
    lines.append(f"Write it now. say, tale and title only in {language_name(code)}; beat and why in English.")
    scene = {
        "type": "object",
        "properties": {"beat": {"type": "string"}, "say": {"type": "string"}, "tale": {"type": "string"}},
        "required": ["beat", "say", "tale"],
        "additionalProperties": False,
    }
    if kind == "quiet":
        props = {"title": {"type": "string"}, "start": scene, "end": scene,
                 "tone": {"type": "string", "enum": ["good", "mixed", "bad"]}}
        required = ["title", "start", "end", "tone"]
    else:
        props = {"title": {"type": "string"}, "start": scene, "why": {"type": "string"}, "win": scene, "lose": scene}
        required = ["title", "start", "why", "win", "lose"]
    schema = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
    return LLMRequest(
        module="episode",
        model=str(mcfg.get("model", "mock")),
        system=load_prompt("episode"),
        messages=[{"role": "user", "content": chr(10).join(lines)}],
        max_tokens=int(mcfg.get("max_tokens", 6000)),
        effort=mcfg.get("effort"),
        json_schema=schema,
    )


BUILDERS = {
    "episode": build_episode,
    "debug": build_debug,
    "letter": build_letter,
    "broadcast": build_broadcast,
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
    voices = payload.get("voices")
    token = _VOICES.set({str(k): str(v) for k, v in voices.items()} if isinstance(voices, dict) else {})
    try:
        return builder(payload, mcfg)
    finally:
        _VOICES.reset(token)
