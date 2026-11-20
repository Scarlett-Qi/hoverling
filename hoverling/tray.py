"""Publish a StatusNotifierItem and a native panel menu on the session bus."""
import gi
gi.require_version("Dbusmenu", "0.4")
from gi.repository import Dbusmenu, Gio, GLib

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"


class PanelIndicator:
    def __init__(self, icon_path, actions, changed):
        self.changed = changed
        self.connected = False
        self.owner = None
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        root = Dbusmenu.Menuitem.new()
        for label, action in actions:
            item = Dbusmenu.Menuitem.new()
            item.property_set("label", label)
            item.connect("item-activated", lambda _, timestamp, callback=action: callback())
            root.child_append(item)
        self.server = Dbusmenu.Server.new(MENU_PATH)
        self.server.set_root(root)

        properties = {
            "Category": ("s", "ApplicationStatus"), "Id": ("s", "hoverling"),
            "Title": ("s", "指译 HoverLing"), "Status": ("s", "Active"),
            "IconName": ("s", str(icon_path)), "Menu": ("o", MENU_PATH),
            "ItemIsMenu": ("b", True),
        }
        xml = "".join(f'<property name="{name}" type="{kind}" access="read"/>'
                      for name, (kind, _) in properties.items())
        info = Gio.DBusNodeInfo.new_for_xml(f'<node><interface name="{ITEM}">{xml}</interface></node>')
        def get_property(bus, sender, path, interface, name):
            return GLib.Variant(*properties[name])
        self.object_id = self.bus.register_object(ITEM_PATH, info.interfaces[0], None, get_property, None)
        self.watch_id = Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                         self.appeared, self.vanished)

    def appeared(self, bus, name, owner):
        self.owner = owner
        bus.call(owner, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                 GLib.Variant("(s)", (ITEM_PATH,)), None, Gio.DBusCallFlags.NONE,
                 5000, None, self.registered, owner)

    def registered(self, bus, result, owner):
        try:
            bus.call_finish(result)
        except GLib.Error:
            return
        if self.owner == owner:
            self.connected = True
            self.changed()

    def vanished(self, *_):
        self.owner = None
        self.connected = False
        self.changed()

    def close(self):
        self.owner = None
        Gio.bus_unwatch_name(self.watch_id)
        self.bus.unregister_object(self.object_id)
        self.server = None
