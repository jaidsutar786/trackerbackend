import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth import get_user_model

User = get_user_model()


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """Handle WebSocket connection"""
        # Get token from query string
        query_string = self.scope['query_string'].decode()
        token = None
        
        if 'token=' in query_string:
            token = query_string.split('token=')[1].split('&')[0]
        
        if not token:
            await self.close()
            return
        
        # Verify JWT token
        try:
            UntypedToken(token)
            self.user = await self.get_user_from_token(token)
            
            if not self.user:
                await self.close()
                return
            
            # Create user-specific group
            self.group_name = f'notifications_{self.user.id}'
            
            # Join user's notification group
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            
            await self.accept()
            
            # Send connection success message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'Connected to notification service'
            }))
            
        except (InvalidToken, TokenError) as e:
            await self.close()
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle messages from WebSocket (optional)"""
        pass
    
    async def notification_message(self, event):
        """Receive notification from channel layer and send to WebSocket"""
        notification = event['notification']
        
        # Send notification to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification': notification
        }))

    async def data_update(self, event):
        """Send data update event to WebSocket (for real-time UI refresh)"""
        await self.send(text_data=json.dumps({
            'type': 'data_update',
            'entity': event['entity'],
            'action': event['action'],
            'data':   event.get('data', {}),
        }))
    
    @database_sync_to_async
    def get_user_from_token(self, token):
        """Get user from JWT token"""
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception:
            return None
