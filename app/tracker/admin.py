"""Django admin for the Squad Achieves league tracker.

Submissions are the workhorse screen here: approvals/rejections write an
AuditEntry (tracker.models.log_audit) and trigger tracker.scoring.recalculate()
so the leaderboard never drifts from what was actually approved. Award and
AuditEntry are derived/append-only data and are read-only in the admin.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import scoring
from .models import (
    Achievement,
    AllowlistItem,
    AuditEntry,
    Award,
    Character,
    CharacterSnapshot,
    ContestVote,
    InviteCode,
    League,
    MemberProfile,
    ProofImage,
    Submission,
    SubmissionComment,
    SubmissionReaction,
    User,
)

admin.site.register(SubmissionComment)
admin.site.register(SubmissionReaction)
admin.site.register(ContestVote)


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "account_name", "main_character_name", "profile_public", "show_on_roster")
    list_filter = ("profile_public", "show_on_roster")
    search_fields = ("user__username", "account_name", "main_character_name")
    autocomplete_fields = ("user",)


@admin.register(CharacterSnapshot)
class CharacterSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "league", "character_name", "class_name", "level", "source", "pob_url", "fetched_at")
    list_filter = ("source", "league")
    search_fields = ("user__username", "character_name")
    readonly_fields = ("fetched_at",)
    autocomplete_fields = ("user", "league")
    actions = ["fetch_from_pob_url"]

    @admin.action(description="Fetch / refresh build from the saved pobb.in URL")
    def fetch_from_pob_url(self, request, queryset):
        from . import roster

        ok = failed = skipped = 0
        for snap in queryset:
            if not snap.pob_url:
                skipped += 1
                continue
            _, error = roster.save_pob_snapshot(snap.user, snap.league, snap.pob_url)
            if error:
                failed += 1
                self.message_user(request, f"{snap.user}: {error}", level="error")
            else:
                ok += 1
        self.message_user(
            request,
            f"Fetched {ok} build(s); {skipped} had no pobb.in URL; {failed} failed.",
        )


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "game", "is_active", "is_hardcore", "is_ssf", "starts_at", "ends_at")
    list_filter = ("game", "is_active", "is_hardcore", "is_ssf")
    search_fields = ("name", "slug", "ggg_id")
    prepopulated_fields = {"slug": ("name",)}
    actions = ["make_active", "recalculate_league"]

    @admin.action(description="Make selected league the active one")
    def make_active(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one league to activate.", level="error")
            return
        league = queryset.first()
        league.activate()
        self.message_user(request, f"'{league.name}' is now the active league.")

    @admin.action(description="Recalculate scores for selected league(s)")
    def recalculate_league(self, request, queryset):
        for league in queryset:
            scoring.recalculate(league=league)
        self.message_user(request, f"Recalculated {queryset.count()} league(s).")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "League profile",
            {"fields": ("display_name", "avatar", "banner_hue", "is_player", "can_submit")},
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "League profile",
            {"fields": ("display_name", "avatar", "banner_hue", "is_player", "can_submit")},
        ),
    )
    list_display = DjangoUserAdmin.list_display + (
        "display_name",
        "banner_hue",
        "is_player",
        "can_submit",
    )
    list_editable = ("can_submit",)
    list_filter = DjangoUserAdmin.list_filter + ("is_player", "can_submit")
    actions = ["block_submissions", "unblock_submissions"]

    @admin.action(description="Block selected players from submitting")
    def block_submissions(self, request, queryset):
        updated = queryset.update(can_submit=False)
        self.message_user(request, f"Blocked {updated} player(s) from submitting.")

    @admin.action(description="Allow selected players to submit")
    def unblock_submissions(self, request, queryset):
        updated = queryset.update(can_submit=True)
        self.message_user(request, f"Unblocked {updated} player(s).")


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "league",
        "label",
        "icon",
        "base_points",
        "requires_allowlist",
        "active",
        "sort_order",
    )
    list_editable = ("sort_order", "active")
    list_filter = ("league", "active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "label", "slug")

    @admin.action(description="Clone selected achievements into the active league")
    def clone_to_active(self, request, queryset):
        active = League.get_active()
        if active is None:
            self.message_user(request, "No active league set.", level="error")
            return
        created = 0
        for ach in queryset:
            if Achievement.objects.filter(league=active, slug=ach.slug).exists():
                continue
            Achievement.objects.create(
                league=active,
                name=ach.name,
                slug=ach.slug,
                label=ach.label,
                description=ach.description,
                icon=ach.icon,
                base_points=ach.base_points,
                verification_rules=ach.verification_rules,
                requires_allowlist=ach.requires_allowlist,
                active=ach.active,
                sort_order=ach.sort_order,
            )
            created += 1
        self.message_user(request, f"Cloned {created} achievement(s) into '{active.name}'.")

    actions = ["clone_to_active"]


@admin.register(AllowlistItem)
class AllowlistItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "note", "active")
    list_editable = ("active",)
    list_filter = ("category", "active")
    search_fields = ("name", "note")


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("character_name", "user", "class_name", "league_name", "retired")
    list_filter = ("retired", "league_name")
    search_fields = ("character_name", "user__username", "user__display_name")
    autocomplete_fields = ("user",)


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "join_url", "created_at", "used_at", "is_expired")
    readonly_fields = ("code", "created_at", "join_url")
    list_filter = ("used_at",)
    search_fields = ("code", "display_name", "note")

    @admin.display(description="Join URL")
    def join_url(self, obj):
        if not obj.pk:
            return "-"
        try:
            path = reverse("invite_redeem_code", args=[obj.code])
        except Exception:
            return "-"
        return format_html('<a href="{0}">{0}</a>', path)


class ProofImageInline(admin.TabularInline):
    model = ProofImage
    extra = 0
    fields = ("preview", "image", "kind", "caption", "uploaded_at")
    readonly_fields = ("preview", "uploaded_at")

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.pk or not obj.image:
            return "-"
        return format_html(
            '<img src="{}" style="max-width:320px;max-height:320px;" />', obj.image.url
        )


class AuditEntryInline(admin.TabularInline):
    model = AuditEntry
    extra = 0
    fields = ("created_at", "actor", "action", "detail")
    readonly_fields = ("created_at", "actor", "action", "detail")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "league",
        "achievement",
        "status",
        "character_level",
        "played_display",
        "kill_count",
        "obtained_at",
        "submitted_at",
    )
    list_filter = ("league", "status", "achievement", "user")
    search_fields = (
        "user__username",
        "user__display_name",
        "character__character_name",
    )
    readonly_fields = ("submitted_at",)
    date_hierarchy = "obtained_at"
    autocomplete_fields = ("user", "league", "character", "achievement", "allowlist_item")
    inlines = [ProofImageInline, AuditEntryInline]
    actions = ["approve_selected", "reject_selected", "mark_contested"]

    @admin.display(description="Played")
    def played_display(self, obj):
        return obj.played_display

    def _set_status(self, request, queryset, status, action_label):
        achievements = set()
        now = timezone.now()
        for submission in queryset:
            submission.status = status
            submission.reviewed_by = request.user
            submission.reviewed_at = now
            submission.save(update_fields=["status", "reviewed_by", "reviewed_at"])
            from .models import log_audit

            log_audit(submission, request.user, status, detail=f"Bulk action: {action_label}")
            achievements.add(submission.achievement_id)

        for achievement_id in achievements:
            scoring.recalculate(Achievement.objects.get(pk=achievement_id))

    @admin.action(description="Approve selected submissions")
    def approve_selected(self, request, queryset):
        self._set_status(request, queryset, Submission.Status.APPROVED, "approved")

    @admin.action(description="Reject selected submissions")
    def reject_selected(self, request, queryset):
        self._set_status(request, queryset, Submission.Status.REJECTED, "rejected")

    @admin.action(description="Mark selected submissions as contested")
    def mark_contested(self, request, queryset):
        self._set_status(request, queryset, Submission.Status.CONTESTED, "contested")

    def save_model(self, request, obj, form, change):
        was_approved = False
        if change and obj.pk:
            was_approved = (
                Submission.objects.filter(pk=obj.pk, status=Submission.Status.APPROVED).exists()
            )
        super().save_model(request, obj, form, change)

        if was_approved and form.changed_data:
            from .models import log_audit

            detail = f"Fields changed by admin: {', '.join(form.changed_data)}"
            log_audit(obj, request.user, AuditEntry.Action.CORRECTED, detail=detail)
            scoring.recalculate(obj.achievement)


@admin.register(Award)
class AwardAdmin(admin.ModelAdmin):
    list_display = ("submission", "award_type", "points", "created_at")
    list_filter = ("award_type",)
    search_fields = ("submission__user__username", "submission__achievement__name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("submission", "action", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("submission__user__username", "submission__achievement__name", "detail")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
