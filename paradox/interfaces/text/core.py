import logging

from paradox.config import config as cfg
from paradox.event import Event, EventLevel, Notification
from paradox.exceptions import InvalidCommand
from paradox.interfaces import AsyncInterface
from paradox.lib import ps
from paradox.lib.event_filter import EventFilter, EventTagFilter, LiveEventRegexpFilter

logger = logging.getLogger("PAI").getChild(__name__)


class AbstractTextInterface(AsyncInterface):
    """Interface Class using any Text interface"""

    def __init__(self, alarm, event_filter: EventFilter, min_level=EventLevel.INFO):
        super().__init__(alarm)

        self.event_filter = event_filter

        self.min_level = min_level
        self.alarm = alarm

    async def run(self):
        ps.subscribe(self.handle_panel_event, "events")
        ps.subscribe(self.handle_notify, "notifications")

    def send_message(self, message: str, level: EventLevel):
        pass

    def notification_filter(self, notification: Notification):
        return notification.level >= self.min_level and notification.sender != self.name

    def handle_notify(self, notification: Notification):
        if self.notification_filter(notification):
            try:
                self.send_message(notification.message, notification.level)
            except Exception as e:
                logger.exception(f"Error handling notification: {e}")

    def handle_panel_event(self, event: Event):
        if self.event_filter.match(event):
            try:
                self.send_message(event.message, event.level)
            except Exception as e:
                logger.exception(f"Error handling event: {e}")

    async def handle_command(self, message_raw):
        message = cfg.COMMAND_ALIAS.get(message_raw, message_raw)

        tokens = message.split(" ")

        if len(tokens) != 3:
            m = f"Invalid: {message_raw}"
            logger.warning(m)
            return m

        if self.alarm is None:
            m = "No alarm registered"
            logger.error(m)
            return m

        element_type = tokens[0].lower()
        element = tokens[1]
        command = self.normalize_command(tokens[2].lower())

        # Process a Zone Command
        if element_type == "zone":
            if not await self.alarm.control_zone(element, command):
                m = f"Zone command error: {element}={command}"
                logger.warning(m)
                return m

        # Process a Partition Command
        elif element_type == "partition":
            if not await self.alarm.control_partition(element, command):
                m = f"Partition command error: {element}={command}"
                logger.warning(m)
                return m

        # Process an Output Command
        elif element_type == "output":
            if not await self.alarm.control_output(element, command):
                m = f"Output command error: {element}={command}"
                logger.warning(m)
                return m
        else:
            m = f"Invalid control element: {element}"
            logger.error(m)
            return m

        logger.info(f"OK: {message_raw}")
        return "OK"

    @staticmethod
    def normalize_command(command):
        command = command.strip().lower()

        if command in ["true", "on", "1", "enable"]:
            return "on"
        elif command in ["false", "off", "0", "disable"]:
            return "off"
        elif command in [
            "pulse",
            "arm",
            "disarm",
            "arm_stay",
            "arm_sleep",
            "bypass",
            "clear_bypass",
        ]:
            return command

        raise InvalidCommand(f'Invalid command: "{command}"')


class ConfiguredAbstractTextInterface(AbstractTextInterface):
    def __init__(
        self, alarm, EVENT_FILTERS, ALLOW_EVENTS, IGNORE_EVENTS, MIN_EVENT_LEVEL
    ):
        if EVENT_FILTERS and (ALLOW_EVENTS or IGNORE_EVENTS):
            raise AssertionError(
                "You can not use *_EVENT_FILTERS and *_ALLOW_EVENTS+*_IGNORE_EVENTS simultaneously"
            )

        min_level = EventLevel.from_name(MIN_EVENT_LEVEL)
        if ALLOW_EVENTS or IGNORE_EVENTS:  # Use if defined, else use TAGS as default
            logger.debug("Using REGEXP Filter")
            event_filter = LiveEventRegexpFilter(ALLOW_EVENTS, IGNORE_EVENTS, min_level)
        else:
            logger.debug("Using Tag Filter")
            event_filter = EventTagFilter(EVENT_FILTERS, min_level)

        super().__init__(alarm, event_filter=event_filter, min_level=min_level)
