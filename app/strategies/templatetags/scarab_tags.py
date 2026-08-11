"""Template access to the scarab catalogue, so views need no extra plumbing.

Usage::

    {% load scarab_tags %}
    <img src="{{ scarab.name|scarab_icon }}" alt="{{ scarab.name }}">
    {% scarab_list as scarabs %}{{ scarabs|json_script:"scarab-data" }}

``scarab_list`` returns the plain python list (not JSON) so the template can pipe
it through Django's ``json_script`` for the picker JS to read.
"""

from __future__ import annotations

from django import template

from .. import scarabs

register = template.Library()


@register.filter(name="scarab_icon")
def scarab_icon(name: str) -> str:
    """Icon URL for a scarab name, "" when unknown."""
    return scarabs.icon_for(name)


@register.filter(name="scarab_desc")
def scarab_desc(name: str) -> str:
    """In-game description for a scarab name, "" when unknown."""
    return scarabs.description_for(name)


@register.simple_tag(name="scarab_list")
def scarab_list() -> list[dict]:
    """Every scarab as ``{"name", "icon", "group", "desc"}``, sorted by (group, name)."""
    return scarabs.all_scarabs()


@register.simple_tag(name="scarab_groups")
def scarab_groups() -> list[str]:
    """Sorted scarab families, for the picker's group filter."""
    return scarabs.groups()
