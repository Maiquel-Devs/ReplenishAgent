from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError

from apps.web.demo import (
    DEMO_ACCOUNTS,
    DEMO_ADMIN_PERMISSIONS,
    DEMO_OPERATOR_PERMISSIONS,
)


class Command(BaseCommand):
    help = "Create or synchronize the local demonstration users."

    def handle(self, *args, **options):
        del args, options
        if not settings.DEBUG:
            raise CommandError("Demo users can only be created when DEBUG=True.")

        permissions = {
            f"{permission.content_type.app_label}.{permission.codename}": permission
            for permission in Permission.objects.select_related("content_type").filter(
                content_type__app_label__in={
                    value.split(".", maxsplit=1)[0]
                    for value in DEMO_ADMIN_PERMISSIONS
                }
            )
        }
        missing_permissions = set(DEMO_ADMIN_PERMISSIONS) - permissions.keys()
        if missing_permissions:
            raise CommandError(
                "Required demonstration permissions are unavailable: "
                + ", ".join(sorted(missing_permissions))
            )

        user_model = get_user_model()
        for account in DEMO_ACCOUNTS:
            user, _ = user_model.objects.get_or_create(username=account["username"])
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.set_password(account["password"])
            user.save()
            user.groups.clear()
            permission_names = (
                DEMO_ADMIN_PERMISSIONS
                if account["is_admin"]
                else DEMO_OPERATOR_PERMISSIONS
            )
            user.user_permissions.set(permissions[name] for name in permission_names)

        self.stdout.write(self.style.SUCCESS("Local demonstration users synchronized."))
