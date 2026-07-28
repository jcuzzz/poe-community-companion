"""Signal handlers that keep derived rows in sync.

The roster/leaderboard views inner-join on ``MemberProfile``, so a User with no
profile is silently invisible everywhere (this bit us when friends were created
straight from the Django admin). Guarantee every User has a MemberProfile the
moment it is created, regardless of whether it came from signup, an invite, or
the admin.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import MemberProfile, User


@receiver(post_save, sender=User, dispatch_uid="tracker_create_member_profile")
def ensure_member_profile(sender, instance, created, **kwargs):
    if created:
        MemberProfile.objects.get_or_create(user=instance)
