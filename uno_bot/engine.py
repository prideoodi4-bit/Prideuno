from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

COLORS = ("R", "Y", "G", "B")
COLOR_EMOJI = {"R": "🔴", "Y": "🟡", "G": "🟢", "B": "🔵"}
COLOR_NAME_AR = {"R": "أحمر", "Y": "أصفر", "G": "أخضر", "B": "أزرق"}

ACTION_LABEL = {
    "skip": "⛔",
    "reverse": "🔄",
    "draw2": "+2",
    "wild": "🎨",
    "wild4": "+4",
}


def make_card(uid: int, color: str | None, kind: str) -> dict[str, Any]:
    return {"uid": uid, "color": color, "kind": kind}


def build_deck(rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.Random()
    deck: list[dict[str, Any]] = []
    uid = 0
    for color in COLORS:
        deck.append(make_card(uid, color, "0")); uid += 1
        for n in range(1, 10):
            deck.append(make_card(uid, color, str(n))); uid += 1
            deck.append(make_card(uid, color, str(n))); uid += 1
        for kind in ("skip", "reverse", "draw2"):
            deck.append(make_card(uid, color, kind)); uid += 1
            deck.append(make_card(uid, color, kind)); uid += 1
    for _ in range(4):
        deck.append(make_card(uid, None, "wild")); uid += 1
        deck.append(make_card(uid, None, "wild4")); uid += 1
    rng.shuffle(deck)
    return deck


def card_label(card: dict[str, Any]) -> str:
    color = card.get("color")
    kind = str(card["kind"])
    prefix = COLOR_EMOJI.get(color, "🌈")
    if kind.isdigit():
        body = kind
    else:
        body = ACTION_LABEL[kind]
    return f"{prefix} {body}"


def card_sort_key(card: dict[str, Any]) -> tuple[int, int]:
    color_order = {"R": 0, "Y": 1, "G": 2, "B": 3, None: 4}
    kind = card["kind"]
    if str(kind).isdigit():
        kind_order = int(kind)
    else:
        kind_order = {"skip": 10, "reverse": 11, "draw2": 12, "wild": 13, "wild4": 14}[kind]
    return color_order.get(card.get("color"), 9), kind_order


def next_index(state: dict[str, Any], steps: int = 1, start: int | None = None) -> int:
    players = state["players"]
    if not players:
        return 0
    idx = state["current_idx"] if start is None else start
    direction = state.get("direction", 1)
    return (idx + direction * steps) % len(players)


def reshuffle_if_needed(state: dict[str, Any]) -> bool:
    if state["deck"]:
        return True
    discard = state["discard"]
    if len(discard) <= 1:
        return False
    top = discard[-1]
    recycled = discard[:-1]
    random.shuffle(recycled)
    state["deck"] = recycled
    state["discard"] = [top]
    return True


def draw_one(state: dict[str, Any]) -> dict[str, Any] | None:
    if not reshuffle_if_needed(state):
        return None
    return state["deck"].pop()


def draw_cards(state: dict[str, Any], player_index: int, count: int) -> list[dict[str, Any]]:
    drawn: list[dict[str, Any]] = []
    for _ in range(count):
        card = draw_one(state)
        if card is None:
            break
        state["players"][player_index]["hand"].append(card)
        drawn.append(card)
    return drawn


def has_current_color_card(hand: list[dict[str, Any]], current_color: str, exclude_uid: int | None = None) -> bool:
    for c in hand:
        if exclude_uid is not None and int(c["uid"]) == int(exclude_uid):
            continue
        if c.get("color") == current_color:
            return True
    return False


def can_play(card: dict[str, Any], state: dict[str, Any], hand: list[dict[str, Any]] | None = None) -> bool:
    kind = card["kind"]
    if kind == "wild":
        return True
    if kind == "wild4":
        if hand is None:
            return True
        return not has_current_color_card(hand, state["current_color"], exclude_uid=int(card["uid"]))

    if card.get("color") == state["current_color"]:
        return True

    top = state["discard"][-1]
    return card["kind"] == top["kind"]


def create_started_state(players: list[dict[str, Any]], rng: random.Random | None = None) -> dict[str, Any]:
    if len(players) < 2:
        raise ValueError("At least 2 players are required")
    rng = rng or random.Random()
    deck = build_deck(rng)
    state: dict[str, Any] = {
        "phase": "playing",
        "players": players,
        "deck": deck,
        "discard": [],
        "current_color": None,
        "current_idx": 0,
        "direction": 1,
        "has_drawn": False,
        "drawn_uid": None,
        "last_event": "بدأت اللعبة 🎮",
        "winner_id": None,
        "hand_messages": {},
    }
    for p in state["players"]:
        p["hand"] = []
        draw_cards(state, state["players"].index(p), 7)

    # Start with a number card to avoid ambiguous first-card action handling.
    number_pos = None
    for i in range(len(state["deck"]) - 1, -1, -1):
        if str(state["deck"][i]["kind"]).isdigit():
            number_pos = i
            break
    if number_pos is None:
        raise RuntimeError("Deck did not contain a number card")
    first = state["deck"].pop(number_pos)
    state["discard"].append(first)
    state["current_color"] = first["color"]
    return state


def find_player_index(state: dict[str, Any], user_id: int) -> int | None:
    for i, p in enumerate(state["players"]):
        if int(p["user_id"]) == int(user_id):
            return i
    return None


def find_card(hand: list[dict[str, Any]], uid: int) -> dict[str, Any] | None:
    for c in hand:
        if int(c["uid"]) == int(uid):
            return c
    return None


def play_card(state: dict[str, Any], user_id: int, uid: int, chosen_color: str | None = None) -> dict[str, Any]:
    """Play a card and mutate state. Returns a small result dict.

    Raises ValueError for invalid actions.
    """
    if state.get("phase") != "playing":
        raise ValueError("اللعبة غير جارية")
    pidx = find_player_index(state, user_id)
    if pidx is None:
        raise ValueError("أنت لست لاعباً في هذه اللعبة")
    if pidx != state["current_idx"]:
        raise ValueError("مو دورك هسه")

    player = state["players"][pidx]
    hand = player["hand"]
    card = find_card(hand, uid)
    if card is None:
        raise ValueError("هذه الورقة غير موجودة بيدك")

    if state.get("has_drawn") and state.get("drawn_uid") is not None and int(uid) != int(state["drawn_uid"]):
        raise ValueError("بعد السحب تگدر تلعب فقط الورقة اللي سحبتها أو تمرر الدور")

    if not can_play(card, state, hand):
        if card["kind"] == "wild4":
            raise ValueError("ما تگدر تلعب +4 لأن عندك ورقة من اللون الحالي")
        raise ValueError("هذه الورقة ما تنلعب على الورقة الحالية")

    if card["kind"] in ("wild", "wild4"):
        if chosen_color not in COLORS:
            return {"needs_color": True, "card": card}
    else:
        chosen_color = card["color"]

    hand.remove(card)
    state["discard"].append(card)
    state["current_color"] = chosen_color
    state["has_drawn"] = False
    state["drawn_uid"] = None

    result: dict[str, Any] = {"played": card, "player_index": pidx, "drawn_to": None, "draw_count": 0}

    if len(hand) == 0:
        state["phase"] = "finished"
        state["winner_id"] = user_id
        state["last_event"] = f"🏆 {player['name']} فاز باللعبة!"
        result["winner"] = player
        return result

    uno = len(hand) == 1
    kind = card["kind"]

    if kind == "skip":
        skipped_idx = next_index(state, 1, pidx)
        state["current_idx"] = next_index(state, 2, pidx)
        state["last_event"] = f"{player['name']} لعب {card_label(card)} — تم تخطي {state['players'][skipped_idx]['name']}"
    elif kind == "reverse":
        state["direction"] *= -1
        if len(state["players"]) == 2:
            state["current_idx"] = pidx
            state["last_event"] = f"{player['name']} لعب {card_label(card)} — رجع الدور إله"
        else:
            state["current_idx"] = next_index(state, 1, pidx)
            state["last_event"] = f"{player['name']} لعب {card_label(card)} — انعكس الاتجاه"
    elif kind in ("draw2", "wild4"):
        target_idx = next_index(state, 1, pidx)
        count = 2 if kind == "draw2" else 4
        draw_cards(state, target_idx, count)
        state["current_idx"] = next_index(state, 2, pidx)
        result["drawn_to"] = state["players"][target_idx]
        result["draw_count"] = count
        state["last_event"] = (
            f"{player['name']} لعب {card_label(card)} — {state['players'][target_idx]['name']} سحب {count} وانطاف دوره"
        )
    else:
        state["current_idx"] = next_index(state, 1, pidx)
        state["last_event"] = f"{player['name']} لعب {card_label(card)}"

    if uno:
        state["last_event"] += "\n🔥 UNO! بقت عنده ورقة وحدة"
        result["uno"] = True

    return result


def draw_for_turn(state: dict[str, Any], user_id: int) -> dict[str, Any]:
    if state.get("phase") != "playing":
        raise ValueError("اللعبة غير جارية")
    pidx = find_player_index(state, user_id)
    if pidx is None or pidx != state["current_idx"]:
        raise ValueError("مو دورك هسه")
    if state.get("has_drawn"):
        raise ValueError("أنت سحبت ورقة بهذا الدور بالفعل")

    card = draw_one(state)
    if card is None:
        state["current_idx"] = next_index(state, 1, pidx)
        state["last_event"] = f"{state['players'][pidx]['name']} حاول يسحب بس الرزمة فارغة"
        return {"card": None, "playable": False, "turn_ended": True}

    hand = state["players"][pidx]["hand"]
    hand.append(card)
    playable = can_play(card, state, hand)
    if playable:
        state["has_drawn"] = True
        state["drawn_uid"] = card["uid"]
        state["last_event"] = f"{state['players'][pidx]['name']} سحب ورقة ويگدر يلعبها أو يمرر"
        return {"card": card, "playable": True, "turn_ended": False}

    state["current_idx"] = next_index(state, 1, pidx)
    state["last_event"] = f"{state['players'][pidx]['name']} سحب ورقة وانتهى دوره"
    return {"card": card, "playable": False, "turn_ended": True}


def pass_after_draw(state: dict[str, Any], user_id: int) -> None:
    pidx = find_player_index(state, user_id)
    if pidx is None or pidx != state["current_idx"]:
        raise ValueError("مو دورك هسه")
    if not state.get("has_drawn"):
        raise ValueError("لازم تسحب أولاً قبل تمرير الدور")
    state["has_drawn"] = False
    state["drawn_uid"] = None
    state["current_idx"] = next_index(state, 1, pidx)
    state["last_event"] = f"{state['players'][pidx]['name']} مرر الدور"
