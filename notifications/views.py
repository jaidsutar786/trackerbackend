from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import Notification, NotificationPreference
from .serializers import NotificationSerializer, NotificationPreferenceSerializer


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(recipient=request.user)
        read = request.query_params.get('read')
        notification_type = request.query_params.get('type')
        limit = request.query_params.get('limit')

        if read in ('true', 'false'):
            notifications = notifications.filter(read=(read == 'true'))
        if notification_type:
            notifications = notifications.filter(notification_type=notification_type)
        if limit and str(limit).isdigit():
            notifications = notifications[:min(int(limit), 100)]

        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, recipient=request.user)
            notification.read = True
            notification.save()
            return Response({'status': 'marked as read'})
        except Notification.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(recipient=request.user, read=False).update(read=True)
        return Response({'status': 'all marked as read'})


class NotificationDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, recipient=request.user)
            notification.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Notification.DoesNotExist:
            return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)


class NotificationSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)
        unread_by_type = {}
        for value, _label in Notification.NOTIFICATION_TYPES:
            count = qs.filter(notification_type=value, read=False).count()
            if count:
                unread_by_type[value] = count
        return Response({
            'total': qs.count(),
            'unread': qs.filter(read=False).count(),
            'unread_by_type': unread_by_type,
        })


class NotificationPreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, user):
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        return pref

    def get(self, request):
        serializer = NotificationPreferenceSerializer(self.get_object(request.user))
        return Response(serializer.data)

    def patch(self, request):
        pref = self.get_object(request.user)
        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
