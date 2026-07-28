"""Backfill MemberProfile rows for any users created without one.

Users made directly in the Django admin never got a MemberProfile, which made
them invisible to the roster (an inner join). The post_save signal now covers
new users; this backfills the existing gap.
"""

from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    User = apps.get_model("tracker", "User")
    MemberProfile = apps.get_model("tracker", "MemberProfile")
    existing = set(MemberProfile.objects.values_list("user_id", flat=True))
    to_create = [
        MemberProfile(user_id=uid)
        for uid in User.objects.values_list("id", flat=True)
        if uid not in existing
    ]
    if to_create:
        MemberProfile.objects.bulk_create(to_create)


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0012_memberprofile_dashboard_char_count"),
    ]

    operations = [
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
    ]
