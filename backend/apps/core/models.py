from django.db import models


class Tenant(models.Model):
    """
    Represents one client company. Every record is tenant-scoped so multiple
    clients can share the same database without data bleeding across boundaries.
    Row-level isolation chosen over schema-level for prototype simplicity; a
    production system with hundreds of tenants would warrant schema-per-tenant.
    """
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
