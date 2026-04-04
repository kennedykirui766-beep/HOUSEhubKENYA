from extensions import db
from models.models import (
    TwoFactorCode, TwoFactorVerification, ServiceProvider, ServiceRequest,
    Appointment, Review, Booking, Payment, Document, MaintenanceRequest,
    Notification, Event, ChatMessage, SupportMessage, SupportTicket,
    Message, House
)
import logging

logger = logging.getLogger(__name__)


def delete_user_and_dependents(user):
    """Delete a user and all dependent records in a safe order.
    This performs explicit deletions instead of relying on ON DELETE CASCADE.
    """
    try:
        # Two-factor codes & verification
        TwoFactorCode.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        TwoFactorVerification.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        # Chat messages (sent by user or addressed to user as agent)
        ChatMessage.query.filter((ChatMessage.user_id == user.id) | (ChatMessage.support_agent_id == user.id)).delete(synchronize_session=False)

        # Support messages and tickets
        SupportMessage.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        SupportTicket.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        # Direct messages (sender or receiver)
        Message.query.filter((Message.sender_id == user.id) | (Message.receiver_id == user.id)).delete(synchronize_session=False)

        # Tenant-related data
        Booking.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Payment.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Document.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        MaintenanceRequest.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Notification.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Event.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        ServiceRequest.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Appointment.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)
        Review.query.filter_by(tenant_id=user.id).delete(synchronize_session=False)

        # If user has service provider profile(s), delete related service data first
        providers = ServiceProvider.query.filter_by(user_id=user.id).all()
        for p in providers:
            ServiceRequest.query.filter_by(service_provider_id=p.id).delete(synchronize_session=False)
            Appointment.query.filter_by(service_provider_id=p.id).delete(synchronize_session=False)
            Review.query.filter_by(service_provider_id=p.id).delete(synchronize_session=False)
        ServiceProvider.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        # Houses owned by user: delete bookings first (already removed above), then houses
        House.query.filter_by(owner_id=user.id).delete(synchronize_session=False)

        # Finally delete the user
        db.session.delete(user)
        db.session.commit()
        logger.info(f"Deleted user {user.id} and dependent records")
        return True, None
    except Exception as e:
        db.session.rollback()
        logger.exception("Error deleting user and dependents")
        return False, str(e)
