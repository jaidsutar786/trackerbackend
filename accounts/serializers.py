from rest_framework import serializers
from .models import User, Workspace


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source='workspace.name', read_only=True, default='')
    workspace_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'role',
            'is_active', 'invite_status', 'invite_sent_at', 'invited_by',
            'workspace', 'workspace_name', 'workspace_permissions',
        ]

    def get_workspace_permissions(self, obj):
        if not obj.workspace_id:
            return {}
        return obj.workspace.permissions_for_role(obj.role)


class CreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'role', 'password']

    def validate_email(self, value):
        email = (value or '').strip().lower()
        if not email:
            raise serializers.ValidationError('Email is required.')
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('This email is already registered.')
        return email

    def create(self, validated_data):
        password = validated_data.pop('password', 'changeme123')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UpdateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, required=False)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'role', 'password', 'is_active']

    def validate_email(self, value):
        email = (value or '').strip().lower()
        if not email:
            raise serializers.ValidationError('Email is required.')
        duplicate = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists()
        if duplicate:
            raise serializers.ValidationError('This email is already registered.')
        return email

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class WorkspaceSerializer(serializers.ModelSerializer):
    seat_limit = serializers.IntegerField(read_only=True)
    project_limit = serializers.IntegerField(read_only=True)
    default_role_permissions = serializers.SerializerMethodField()
    effective_role_permissions = serializers.SerializerMethodField()
    effective_plan = serializers.CharField(read_only=True)

    class Meta:
        model = Workspace
        fields = [
            'id', 'name', 'slug', 'plan', 'subscription_status', 'billing_email',
            'trial_ends_at', 'current_period_end', 'billing_customer_id',
            'billing_subscription_id', 'role_permissions', 'default_role_permissions',
            'effective_role_permissions', 'effective_plan', 'seat_limit', 'project_limit',
        ]
        read_only_fields = [
            'id', 'slug', 'plan', 'subscription_status', 'trial_ends_at',
            'current_period_end', 'billing_customer_id', 'billing_subscription_id',
            'default_role_permissions', 'effective_role_permissions', 'effective_plan',
            'seat_limit', 'project_limit',
        ]

    def get_default_role_permissions(self, obj):
        return obj.DEFAULT_ROLE_PERMISSIONS

    def get_effective_role_permissions(self, obj):
        roles = [role for role, _label in User.ROLE_CHOICES if role != 'admin']
        return {role: obj.permissions_for_role(role) for role in roles}

    def validate_role_permissions(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Permissions must be an object keyed by role.')
        valid_roles = {role for role, _label in User.ROLE_CHOICES if role != 'admin'}
        invalid_roles = set(value) - valid_roles
        if invalid_roles:
            raise serializers.ValidationError('Only non-admin role permissions can be customized.')
        for role, permissions in value.items():
            if not isinstance(permissions, dict):
                raise serializers.ValidationError(f'Permissions for {role} must be an object.')
            invalid_modules = set(permissions) - set(Workspace.PERMISSION_MODULES)
            if invalid_modules or any(not isinstance(allowed, bool) for allowed in permissions.values()):
                raise serializers.ValidationError(f'Permissions for {role} contain invalid module settings.')
        return value
