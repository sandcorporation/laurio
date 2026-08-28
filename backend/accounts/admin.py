from django.contrib import admin

from .models import BlacklistedToken, DeveloperProfile, RefreshToken, SocialAccount, SponsorProfile


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "provider_uid", "connected_at")
    list_filter = ("provider",)
    search_fields = ("provider_uid", "user__username")


@admin.register(SponsorProfile)
class SponsorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "created_at")


@admin.register(DeveloperProfile)
class DeveloperProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "created_at")


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "jti", "expires_at", "revoked_at", "created_at")
    list_filter = ("revoked_at",)


@admin.register(BlacklistedToken)
class BlacklistedTokenAdmin(admin.ModelAdmin):
    list_display = ("jti", "expires_at", "blacklisted_at")
