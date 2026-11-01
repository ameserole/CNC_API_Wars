"""Client-side model of what the script's player knows, kept current from snapshots and events."""

from __future__ import annotations

from typing import Any

Obj = dict[str, Any]


class World:
    def __init__(self) -> None:
        self.frame = 0
        self.me: dict[str, Any] = {}
        self.units: dict[int, Obj] = {}             # own objects
        self.visible: dict[int, Obj] = {}           # other players' objects we can see now
        self.known_structures: dict[int, Obj] = {}  # other players' structures seen so far: "visible" now or remembered
        self.templates: dict[str, dict] = {}        # template name -> template_info / catalog entry
        self.game_info: dict | None = None
        self.catalog: dict | None = None
        self.result: str | None = None              # "victory" / "defeat" once the game is over
        self.enemies_seen: dict[int, dict] = {}     # enemy objects ever spotted: last info + "visible"

    # -- wiring -------------------------------------------------------------------------------

    def attach(self, client) -> "World":
        """Keeps this model updated from the client's events."""
        client.on("snapshot", self.apply_snapshot)
        for name in ("unit_destroyed", "unit_removed", "money_changed", "power_changed", "rank_changed", "game_over",
                     "enemy_spotted", "enemy_lost_from_view", "enemy_destroyed"):
            client.on(name, self.apply_event)
        return self

    async def load(self, client) -> "World":
        """Fetches the static match data, and template details for everything currently known."""
        self.game_info = await client.game_info()
        self.apply_catalog(await client.catalog())
        self.apply_snapshot(await client.state())
        await self.refresh_templates(client)
        return self

    async def refresh_templates(self, client) -> None:
        names = self.unknown_templates()
        if names:
            info = await client.template_info(sorted(names))
            self.templates.update(info["templates"])

    # -- updates ------------------------------------------------------------------------------

    def apply_snapshot(self, snapshot: dict) -> None:
        self.frame = snapshot.get("frame", self.frame)
        self.me = dict(snapshot.get("self", {}))
        self.units = {u["id"]: u for u in snapshot.get("units", [])}
        self.visible = {o["id"]: o for o in snapshot.get("visible", [])}
        self.known_structures = {o["id"]: o for o in snapshot.get("known_structures", [])}

    def apply_event(self, event: dict) -> None:
        name = event.get("event")
        self.frame = max(self.frame, event.get("frame", self.frame))
        if name in ("unit_destroyed", "unit_removed"):
            self.units.pop(event["id"], None)
        elif name == "enemy_spotted":
            self.enemies_seen[event["id"]] = {"template": event["template"], "owner": event.get("owner"),
                                              "pos": event["pos"], "frame": event["frame"], "visible": True}
        elif name == "enemy_lost_from_view":
            entry = self.enemies_seen.setdefault(event["id"], {"template": event["template"]})
            entry.update(pos=event["last_pos"], frame=event["frame"], visible=False)
        elif name == "enemy_destroyed":
            self.enemies_seen.pop(event["id"], None)
        elif name == "money_changed":
            self.me["money"] = event["money"]
        elif name == "power_changed":
            self.me["power"] = {"produced": event["produced"], "consumed": event["consumed"]}
        elif name == "rank_changed":
            self.me["rank"] = event["rank"]
            self.me["science_points"] = event["science_points"]
        elif name == "game_over":
            self.result = event["result"]

    def apply_catalog(self, catalog: dict) -> None:
        self.catalog = catalog
        for entry in catalog.get("structures", []) + catalog.get("units", []):
            self.templates[entry["name"]] = entry

    # -- queries ------------------------------------------------------------------------------

    @property
    def money(self) -> int | None:
        return self.me.get("money")

    @property
    def power(self) -> dict | None:
        return self.me.get("power")

    def kinds(self, template: str) -> set[str]:
        return set(self.templates.get(template, {}).get("kinds", ()))

    def unknown_templates(self) -> set[str]:
        seen = {o["template"] for group in (self.units, self.visible, self.known_structures) for o in group.values()}
        return seen - set(self.templates)

    def mine(self, template: str | None = None, kind: str | None = None) -> list[Obj]:
        return self._filter(self.units.values(), template, kind)

    def enemies(self, template: str | None = None, kind: str | None = None) -> list[Obj]:
        return self._filter((o for o in self.visible.values() if o.get("owner") in self._enemy_indices()), template, kind)

    def enemy_structures(self, template: str | None = None, kind: str | None = None) -> list[Obj]:
        """Every enemy structure the player knows of, whether in sight now or remembered through fog."""
        return self._filter((o for o in self.known_structures.values() if o.get("owner") in self._enemy_indices()),
                            template, kind)

    def _enemy_indices(self) -> set[int]:
        return {p["index"] for p in (self.game_info or {}).get("players", []) if p["relation"] == "enemy"}

    def _filter(self, objects, template, kind) -> list[Obj]:
        return [o for o in objects
                if (template is None or o["template"] == template)
                and (kind is None or kind in self.kinds(o["template"]))]
