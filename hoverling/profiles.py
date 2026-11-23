"""AI configurations edited together in one settings dialog."""

AI_FIELDS = ("api_base", "model", "api_key")


class AIProfiles:
    def __init__(self, values):
        saved = values.get("ai_profiles")
        self.items = []
        if isinstance(saved, list):
            for item in saved:
                if isinstance(item, dict):
                    self.items.append({key: item.get(key, "") if isinstance(item.get(key), str) else ""
                                       for key in ("name", *AI_FIELDS)})
        if not self.items:
            self.items.append({"name": "默认配置", **{key: values[key] for key in AI_FIELDS}})
        index = values.get("active_ai_profile")
        self.index = index if type(index) is int and 0 <= index < len(self.items) else 0

    @property
    def current(self):
        return self.items[self.index]

    def labels(self):
        return [item["name"] or f"配置 {i}" for i, item in enumerate(self.items, 1)]

    def add(self):
        names = set(self.labels())
        number = len(self.items) + 1
        while f"配置 {number}" in names:
            number += 1
        self.items.append({"name": f"配置 {number}", **dict.fromkeys(AI_FIELDS, "")})
        self.index = len(self.items) - 1

    def remove(self):
        if len(self.items) > 1:
            self.items.pop(self.index)
            self.index = min(self.index, len(self.items) - 1)

    def settings(self):
        return {"ai_profiles": self.items, "active_ai_profile": self.index,
                **{key: self.current[key] for key in AI_FIELDS}}
