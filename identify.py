from __future__ import annotations

import math
from typing import Any, Optional

import color


def _trait_level(actor: Any, trait_name: str, default: int = 1) -> int:
	try:
		return int(actor.level.traits.get(trait_name, {}).get("level", default) or default)
	except Exception:
		return default


def _ensure_state(actor: Any) -> tuple[set[str], dict[str, dict[str, Any]]]:
	identified = getattr(actor, "identified_item_keys", None)
	if not isinstance(identified, set):
		identified = set(identified or [])
		actor.identified_item_keys = identified

	jobs = getattr(actor, "identification_jobs", None)
	if not isinstance(jobs, dict):
		jobs = {}
		actor.identification_jobs = jobs

	return identified, jobs


def _job_matches_item(job: Any, item: Any) -> bool:
	if not isinstance(job, dict):
		return False
	tracked_item_id = job.get("item_id")
	return tracked_item_id is None or int(tracked_item_id) == id(item)


def _job_display_name(job: Any, fallback: str = "item") -> str:
	if not isinstance(job, dict):
		return fallback
	return str(job.get("display_name", fallback) or fallback)


def _item_key(item: Any) -> str:
	instance_key = str(getattr(item, "identification_instance_key", "") or "").strip().lower()
	if instance_key:
		return instance_key

	explicit = str(getattr(item, "identification_key", "") or "").strip().lower()
	if explicit:
		instance_key = f"{explicit}#{id(item)}"
	else:
		name = str(getattr(item, "name", "") or "").strip().lower() or "item"
		instance_key = f"{name}#{id(item)}"

	try:
		item.identification_instance_key = instance_key
	except Exception:
		pass
	return instance_key


def _item_tags(item: Any) -> set[str]:
	return {
		str(tag).strip().lower()
		for tag in getattr(item, "tags", []) or []
		if str(tag).strip()
	}


def _has_hidden_modifiers(item: Any) -> bool:
	try:
		if int(getattr(item, "enchantment_level", 0) or 0) > 0:
			return True
	except Exception:
		pass

	try:
		enchants = getattr(item, "enchantments", None) or []
		if len(enchants) > 0:
			return True
	except Exception:
		pass

	return False


def _is_potion(item: Any) -> bool:
	tags = _item_tags(item)
	if "potion" in tags:
		return True
	return "potion" in str(getattr(item, "name", "") or "").strip().lower()


def _has_identify_tag(item: Any) -> bool:
	tags = _item_tags(item)
	return any(tag in tags for tag in ("identifiable", "can_be_identified", "can_identify"))


def _is_equipment_item(item: Any) -> bool:
	return getattr(item, "equippable", None) is not None


def get_item_category(item: Any) -> Optional[str]:
	if _is_potion(item):
		return "potion"
	return None


def _category_label(item: Any) -> str:
	cat = get_item_category(item)
	if cat == "potion":
		return "potion"
	return "item"


def is_identifiable(item: Any) -> bool:
	explicit = getattr(item, "identifiable", None)
	if explicit is not None:
		return bool(explicit)

	if _has_identify_tag(item):
		return True

	# Default behavior: only gear and potions participate in identification.
	return _is_equipment_item(item) or _is_potion(item)


def is_identified(actor: Any, item: Any) -> bool:
	if not is_identifiable(item):
		return True
	identified, _ = _ensure_state(actor)
	return _item_key(item) in identified


def _difficulty(item: Any) -> int:
	return max(1, int(getattr(item, "identification_level", 1) or 1))


def required_turns(actor: Any, item: Any) -> int:
	diff = _difficulty(item)
	id_level = _trait_level(actor, "identification")
	int_level = _trait_level(actor, "intellect")

	base_turns = 2 + (diff * 10)
	speed = 1.0 + max(0, id_level - 1) * 0.30 + max(0, int_level - 1) * 0.15
	return max(2, int(math.ceil(base_turns / max(0.25, speed))))


def _begin_identification_job(actor: Any, item: Any) -> dict[str, Any]:
	turns = required_turns(actor, item)
	return {
		"category": get_item_category(item),
		"display_name": str(getattr(item, "name", "Item") or "Item"),
		"difficulty": _difficulty(item),
		"turns_total": turns,
		"turns_left": turns,
		"item_id": id(item),
	}


def _find_next_auto_item(actor: Any) -> Optional[Any]:
	inventory_items = getattr(getattr(actor, "inventory", None), "items", []) or []
	for item in inventory_items:
		if item is None:
			continue
		if not is_identifiable(item):
			continue
		if is_identified(actor, item):
			continue
		return item
	return None


def get_progress(actor: Any, item: Any) -> Optional[dict[str, int]]:
	if not is_identifiable(item):
		return None

	_, jobs = _ensure_state(actor)
	job = jobs.get(_item_key(item))
	if not _job_matches_item(job, item):
		return None

	total = max(1, int(job.get("turns_total", 1) or 1))
	left = max(0, int(job.get("turns_left", total) or total))
	done = max(0, total - left)
	pct = int(round((done / total) * 100))
	return {
		"turns_total": total,
		"turns_left": left,
		"turns_done": done,
		"percent": max(0, min(100, pct)),
	}


def start_identification(actor: Any, item: Any) -> tuple[bool, str]:
	if not is_identifiable(item):
		return False, "You cannot identify that item."

	if is_identified(actor, item):
		return False, f"You already know this {_category_label(item)}."

	_, jobs = _ensure_state(actor)
	key = _item_key(item)
	if key in jobs:
		return True, ""
	action_text = "begin"
	if jobs:
		jobs.clear()
		action_text = "focus on"

	job = _begin_identification_job(actor, item)
	jobs[key] = job
	turns = int(job["turns_total"])
	return True, f"You {action_text} identifying the {_category_label(item)} ({turns} turns)."


def cancel_identification_for_item(actor: Any, item: Any, engine: Any = None, quiet: bool = True) -> bool:
	"""Cancel an in-progress identification job bound to this exact item instance."""
	_, jobs = _ensure_state(actor)
	key = _item_key(item)
	job = jobs.get(key)
	if not _job_matches_item(job, item):
		return False

	jobs.pop(key, None)
	if not quiet and engine and hasattr(engine, "message_log"):
		display_name = _job_display_name(job)
		engine.message_log.add_message(f"You stop identifying the {display_name}.", color.gray)
	return True


def force_identify_item(actor: Any, item: Any, engine: Any = None, announce: bool = False) -> bool:
	"""Immediately mark a specific item as identified and clear its active job."""
	if not is_identifiable(item):
		return False

	identified, jobs = _ensure_state(actor)
	key = _item_key(item)
	job = jobs.get(key)
	if _job_matches_item(job, item):
		jobs.pop(key, None)

	if key in identified:
		return False

	identified.add(key)
	if announce and engine and hasattr(engine, "message_log"):
		display_name = str(getattr(item, "name", "item") or "item")
		engine.message_log.add_message(f"You identify the {display_name}.", color.light_blue)
	return True


def _award_identification_xp(actor: Any, difficulty: int) -> None:
	level = getattr(actor, "level", None)
	if not level or not hasattr(level, "add_xp"):
		return

	base = 8 + (int(difficulty) * 6)
	intellect = max(1, base // 2)
	try:
		level.add_xp({"identification": base, "intellect": intellect})
	except Exception:
		pass


def tick_identification(actor: Any, engine: Any) -> None:
	identified, jobs = _ensure_state(actor)
	if not jobs:
		next_item = _find_next_auto_item(actor)
		if next_item is None:
			return
		jobs[_item_key(next_item)] = _begin_identification_job(actor, next_item)

	inventory_items = getattr(getattr(actor, "inventory", None), "items", []) or []
	inventory_item_ids = {id(i) for i in inventory_items if i is not None}

	# Identification runs strictly one item at a time. If multiple jobs somehow
	# exist, keep the oldest/current first job and discard the rest.
	if len(jobs) > 1:
		first_key = next(iter(jobs))
		for extra_key in list(jobs.keys()):
			if extra_key != first_key:
				jobs.pop(extra_key, None)

	canceled: list[tuple[str, dict[str, Any]]] = []
	completed: list[tuple[str, dict[str, Any]]] = []
	for key, job in list(jobs.items()):
		tracked_item_id = job.get("item_id") if isinstance(job, dict) else None
		if tracked_item_id is not None and int(tracked_item_id) not in inventory_item_ids:
			canceled.append((key, job))
			continue

		left = max(0, int(job.get("turns_left", 0) or 0))
		if left <= 0:
			completed.append((key, job))
			continue

		job["turns_left"] = left - 1
		if job["turns_left"] <= 0:
			completed.append((key, job))

	for key, job in canceled:
		jobs.pop(key, None)
		if engine and hasattr(engine, "message_log"):
			display_name = _job_display_name(job)
			engine.message_log.add_message(f"You stop identifying the {display_name}.", color.gray)

	for key, job in completed:
		jobs.pop(key, None)
		identified.add(key)

		display_name = _job_display_name(job)
		if engine and hasattr(engine, "message_log"):
			engine.message_log.add_message(
				f"You identify the {display_name}.",
				color.light_blue,
			)
		_award_identification_xp(actor, int(job.get("difficulty", 1) or 1))


def get_display_name(actor: Any, item: Any) -> str:
	real_name = str(getattr(item, "name", "") or "")
	if not is_identifiable(item):
		return real_name
	if is_identified(actor, item):
		return real_name

	if _has_hidden_modifiers(item):
		base_name = str(getattr(item, "base_name", "") or "").strip()
		if base_name:
			return base_name
		return "Ordinary Item"

	# Custom unknown labels still take precedence for explicitly mysterious items.
	unknown_name = str(getattr(item, "unknown_name", "") or "").strip()
	if unknown_name:
		return unknown_name

	# Mundane unidentified items still look normal; identify can confirm them.
	return real_name


def get_display_color(actor: Any, item: Any) -> tuple[int, int, int]:
	default = tuple(getattr(item, "color", (200, 180, 100)))
	if not is_identifiable(item) or is_identified(actor, item):
		return default
	if _has_hidden_modifiers(item):
		return tuple(getattr(item, "base_color", default))
	return default


def get_display_rarity_color(actor: Any, item: Any) -> tuple[int, int, int]:
	default = tuple(getattr(item, "rarity_color", (220, 190, 120)))
	if not is_identifiable(item) or is_identified(actor, item):
		return default
	if _has_hidden_modifiers(item):
		return tuple(getattr(item, "base_rarity_color", default))
	return default


def get_display_description(actor: Any, item: Any) -> str:
	if not is_identifiable(item):
		return str(getattr(item, "description", "") or "")
	if is_identified(actor, item):
		return str(getattr(item, "description", "") or "")

	custom = str(getattr(item, "unknown_description", "") or "").strip()
	if custom:
		return custom

	if _has_hidden_modifiers(item):
		return "Nothing obviously unusual at a glance."

	return item.get_description(observer=actor)
