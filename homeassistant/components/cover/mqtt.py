"""
Support for MQTT cover devices.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/cover.mqtt/
"""
import logging
from typing import Optional

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.components import mqtt, cover
from homeassistant.components.cover import (
    CoverDevice, ATTR_TILT_POSITION, SUPPORT_OPEN_TILT,
    SUPPORT_CLOSE_TILT, SUPPORT_STOP_TILT, SUPPORT_SET_TILT_POSITION,
    SUPPORT_OPEN, SUPPORT_CLOSE, SUPPORT_STOP, SUPPORT_SET_POSITION,
    ATTR_POSITION)
from homeassistant.exceptions import TemplateError
from homeassistant.const import (
    CONF_NAME, CONF_VALUE_TEMPLATE, CONF_OPTIMISTIC, STATE_OPEN,
    STATE_CLOSED, STATE_UNKNOWN, CONF_DEVICE)
from homeassistant.components.mqtt import (
    ATTR_DISCOVERY_HASH, CONF_AVAILABILITY_TOPIC, CONF_STATE_TOPIC,
    CONF_COMMAND_TOPIC, CONF_PAYLOAD_AVAILABLE, CONF_PAYLOAD_NOT_AVAILABLE,
    CONF_QOS, CONF_RETAIN, valid_publish_topic, valid_subscribe_topic,
    MqttAvailability, MqttDiscoveryUpdate, MqttEntityDeviceInfo)
from homeassistant.components.mqtt.discovery import MQTT_DISCOVERY_NEW
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import HomeAssistantType, ConfigType

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['mqtt']

CONF_GET_POSITION_TOPIC = 'position_topic'

CONF_TILT_COMMAND_TOPIC = 'tilt_command_topic'
CONF_TILT_STATUS_TOPIC = 'tilt_status_topic'
CONF_SET_POSITION_TOPIC = 'set_position_topic'
CONF_SET_POSITION_TEMPLATE = 'set_position_template'

CONF_PAYLOAD_OPEN = 'payload_open'
CONF_PAYLOAD_CLOSE = 'payload_close'
CONF_PAYLOAD_STOP = 'payload_stop'
CONF_STATE_OPEN = 'state_open'
CONF_STATE_CLOSED = 'state_closed'
CONF_POSITION_OPEN = 'position_open'
CONF_POSITION_CLOSED = 'position_closed'
CONF_TILT_CLOSED_POSITION = 'tilt_closed_value'
CONF_TILT_OPEN_POSITION = 'tilt_opened_value'
CONF_TILT_MIN = 'tilt_min'
CONF_TILT_MAX = 'tilt_max'
CONF_TILT_STATE_OPTIMISTIC = 'tilt_optimistic'
CONF_TILT_INVERT_STATE = 'tilt_invert_state'
CONF_UNIQUE_ID = 'unique_id'

TILT_PAYLOAD = "tilt"
COVER_PAYLOAD = "cover"

DEFAULT_NAME = 'MQTT Cover'
DEFAULT_PAYLOAD_OPEN = 'OPEN'
DEFAULT_PAYLOAD_CLOSE = 'CLOSE'
DEFAULT_PAYLOAD_STOP = 'STOP'
DEFAULT_POSITION_OPEN = 100
DEFAULT_POSITION_CLOSED = 0
DEFAULT_OPTIMISTIC = False
DEFAULT_RETAIN = False
DEFAULT_TILT_CLOSED_POSITION = 0
DEFAULT_TILT_OPEN_POSITION = 100
DEFAULT_TILT_MIN = 0
DEFAULT_TILT_MAX = 100
DEFAULT_TILT_OPTIMISTIC = False
DEFAULT_TILT_INVERT_STATE = False

OPEN_CLOSE_FEATURES = (SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP)
TILT_FEATURES = (SUPPORT_OPEN_TILT | SUPPORT_CLOSE_TILT | SUPPORT_STOP_TILT |
                 SUPPORT_SET_TILT_POSITION)


def validate_options(value):
    """Validate options.

    If set postion topic is set then get position topic is set as well.
    """
    if (CONF_SET_POSITION_TOPIC in value and
            CONF_GET_POSITION_TOPIC not in value):
        raise vol.Invalid(
            "set_position_topic must be set together with position_topic.")
    return value


PLATFORM_SCHEMA = vol.All(mqtt.MQTT_BASE_PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_COMMAND_TOPIC): valid_publish_topic,
    vol.Optional(CONF_SET_POSITION_TOPIC): valid_publish_topic,
    vol.Optional(CONF_SET_POSITION_TEMPLATE): cv.template,
    vol.Optional(CONF_RETAIN, default=DEFAULT_RETAIN): cv.boolean,
    vol.Optional(CONF_GET_POSITION_TOPIC): valid_subscribe_topic,
    vol.Optional(CONF_STATE_TOPIC): valid_subscribe_topic,
    vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PAYLOAD_OPEN, default=DEFAULT_PAYLOAD_OPEN): cv.string,
    vol.Optional(CONF_PAYLOAD_CLOSE, default=DEFAULT_PAYLOAD_CLOSE): cv.string,
    vol.Optional(CONF_PAYLOAD_STOP, default=DEFAULT_PAYLOAD_STOP): cv.string,
    vol.Optional(CONF_STATE_OPEN, default=STATE_OPEN): cv.string,
    vol.Optional(CONF_STATE_CLOSED, default=STATE_CLOSED): cv.string,
    vol.Optional(CONF_POSITION_OPEN,
                 default=DEFAULT_POSITION_OPEN): int,
    vol.Optional(CONF_POSITION_CLOSED,
                 default=DEFAULT_POSITION_CLOSED): int,
    vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
    vol.Optional(CONF_TILT_COMMAND_TOPIC): valid_publish_topic,
    vol.Optional(CONF_TILT_STATUS_TOPIC): valid_subscribe_topic,
    vol.Optional(CONF_TILT_CLOSED_POSITION,
                 default=DEFAULT_TILT_CLOSED_POSITION): int,
    vol.Optional(CONF_TILT_OPEN_POSITION,
                 default=DEFAULT_TILT_OPEN_POSITION): int,
    vol.Optional(CONF_TILT_MIN, default=DEFAULT_TILT_MIN): int,
    vol.Optional(CONF_TILT_MAX, default=DEFAULT_TILT_MAX): int,
    vol.Optional(CONF_TILT_STATE_OPTIMISTIC,
                 default=DEFAULT_TILT_OPTIMISTIC): cv.boolean,
    vol.Optional(CONF_TILT_INVERT_STATE,
                 default=DEFAULT_TILT_INVERT_STATE): cv.boolean,
    vol.Optional(CONF_UNIQUE_ID): cv.string,
    vol.Optional(CONF_DEVICE): mqtt.MQTT_ENTITY_DEVICE_INFO_SCHEMA,
}).extend(mqtt.MQTT_AVAILABILITY_SCHEMA.schema), validate_options)


async def async_setup_platform(hass: HomeAssistantType, config: ConfigType,
                               async_add_entities, discovery_info=None):
    """Set up MQTT cover through configuration.yaml."""
    await _async_setup_entity(hass, config, async_add_entities)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up MQTT cover dynamically through MQTT discovery."""
    async def async_discover(discovery_payload):
        """Discover and add an MQTT cover."""
        config = PLATFORM_SCHEMA(discovery_payload)
        await _async_setup_entity(hass, config, async_add_entities,
                                  discovery_payload[ATTR_DISCOVERY_HASH])

    async_dispatcher_connect(
        hass, MQTT_DISCOVERY_NEW.format(cover.DOMAIN, 'mqtt'),
        async_discover)


async def _async_setup_entity(hass, config, async_add_entities,
                              discovery_hash=None):
    """Set up the MQTT Cover."""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass
    set_position_template = config.get(CONF_SET_POSITION_TEMPLATE)
    if set_position_template is not None:
        set_position_template.hass = hass

    async_add_entities([MqttCover(
        config.get(CONF_NAME),
        config.get(CONF_STATE_TOPIC),
        config.get(CONF_GET_POSITION_TOPIC),
        config.get(CONF_COMMAND_TOPIC),
        config.get(CONF_AVAILABILITY_TOPIC),
        config.get(CONF_TILT_COMMAND_TOPIC),
        config.get(CONF_TILT_STATUS_TOPIC),
        config.get(CONF_QOS),
        config.get(CONF_RETAIN),
        config.get(CONF_STATE_OPEN),
        config.get(CONF_STATE_CLOSED),
        config.get(CONF_POSITION_OPEN),
        config.get(CONF_POSITION_CLOSED),
        config.get(CONF_PAYLOAD_OPEN),
        config.get(CONF_PAYLOAD_CLOSE),
        config.get(CONF_PAYLOAD_STOP),
        config.get(CONF_PAYLOAD_AVAILABLE),
        config.get(CONF_PAYLOAD_NOT_AVAILABLE),
        config.get(CONF_OPTIMISTIC),
        value_template,
        config.get(CONF_TILT_OPEN_POSITION),
        config.get(CONF_TILT_CLOSED_POSITION),
        config.get(CONF_TILT_MIN),
        config.get(CONF_TILT_MAX),
        config.get(CONF_TILT_STATE_OPTIMISTIC),
        config.get(CONF_TILT_INVERT_STATE),
        config.get(CONF_SET_POSITION_TOPIC),
        set_position_template,
        config.get(CONF_UNIQUE_ID),
        config.get(CONF_DEVICE),
        discovery_hash
    )])


class MqttCover(MqttAvailability, MqttDiscoveryUpdate, MqttEntityDeviceInfo,
                CoverDevice):
    """Representation of a cover that can be controlled using MQTT."""

    def __init__(self, name, state_topic, get_position_topic,
                 command_topic, availability_topic,
                 tilt_command_topic, tilt_status_topic, qos, retain,
                 state_open, state_closed, position_open, position_closed,
                 payload_open, payload_close, payload_stop, payload_available,
                 payload_not_available, optimistic, value_template,
                 tilt_open_position, tilt_closed_position, tilt_min, tilt_max,
                 tilt_optimistic, tilt_invert, set_position_topic,
                 set_position_template, unique_id: Optional[str],
                 device_config: Optional[ConfigType], discovery_hash):
        """Initialize the cover."""
        MqttAvailability.__init__(self, availability_topic, qos,
                                  payload_available, payload_not_available)
        MqttDiscoveryUpdate.__init__(self, discovery_hash)
        MqttEntityDeviceInfo.__init__(self, device_config)
        self._position = None
        self._state = None
        self._name = name
        self._state_topic = state_topic
        self._get_position_topic = get_position_topic
        self._command_topic = command_topic
        self._tilt_command_topic = tilt_command_topic
        self._tilt_status_topic = tilt_status_topic
        self._qos = qos
        self._payload_open = payload_open
        self._payload_close = payload_close
        self._payload_stop = payload_stop
        self._state_open = state_open
        self._state_closed = state_closed
        self._position_open = position_open
        self._position_closed = position_closed
        self._retain = retain
        self._tilt_open_position = tilt_open_position
        self._tilt_closed_position = tilt_closed_position
        self._optimistic = (optimistic or (state_topic is None and
                                           get_position_topic is None))
        self._template = value_template
        self._tilt_value = None
        self._tilt_min = tilt_min
        self._tilt_max = tilt_max
        self._tilt_optimistic = tilt_optimistic
        self._tilt_invert = tilt_invert
        self._set_position_topic = set_position_topic
        self._set_position_template = set_position_template
        self._unique_id = unique_id
        self._discovery_hash = discovery_hash

    async def async_added_to_hass(self):
        """Subscribe MQTT events."""
        await MqttAvailability.async_added_to_hass(self)
        await MqttDiscoveryUpdate.async_added_to_hass(self)

        @callback
        def tilt_updated(topic, payload, qos):
            """Handle tilt updates."""
            if (payload.isnumeric() and
                    self._tilt_min <= int(payload) <= self._tilt_max):

                level = self.find_percentage_in_range(float(payload))
                self._tilt_value = level
                self.async_schedule_update_ha_state()

        @callback
        def state_message_received(topic, payload, qos):
            """Handle new MQTT state messages."""
            if self._template is not None:
                payload = self._template.async_render_with_possible_json_value(
                    payload)

            if payload == self._state_open:
                self._state = False
            elif payload == self._state_closed:
                self._state = True
            else:
                _LOGGER.warning("Payload is not True or False: %s", payload)
                return
            self.async_schedule_update_ha_state()

        @callback
        def position_message_received(topic, payload, qos):
            """Handle new MQTT state messages."""
            if self._template is not None:
                payload = self._template.async_render_with_possible_json_value(
                    payload)

            if payload.isnumeric():
                percentage_payload = self.find_percentage_in_range(
                    float(payload), COVER_PAYLOAD)
                self._position = percentage_payload
                self._state = percentage_payload == DEFAULT_POSITION_CLOSED
            else:
                _LOGGER.warning(
                    "Payload is not integer within range: %s",
                    payload)
                return
            self.async_schedule_update_ha_state()

        if self._get_position_topic:
            await mqtt.async_subscribe(
                self.hass, self._get_position_topic,
                position_message_received, self._qos)
        elif self._state_topic:
            await mqtt.async_subscribe(
                self.hass, self._state_topic,
                state_message_received, self._qos)
        else:
            # Force into optimistic mode.
            self._optimistic = True

        if self._tilt_status_topic is None:
            self._tilt_optimistic = True
        else:
            self._tilt_optimistic = False
            self._tilt_value = STATE_UNKNOWN
            await mqtt.async_subscribe(
                self.hass, self._tilt_status_topic, tilt_updated, self._qos)

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic

    @property
    def name(self):
        """Return the name of the cover."""
        return self._name

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self._state

    @property
    def current_cover_position(self):
        """Return current position of cover.

        None is unknown, 0 is closed, 100 is fully open.
        """
        return self._position

    @property
    def current_cover_tilt_position(self):
        """Return current position of cover tilt."""
        return self._tilt_value

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = 0
        if self._command_topic is not None:
            supported_features = OPEN_CLOSE_FEATURES

        if self._set_position_topic is not None:
            supported_features |= SUPPORT_SET_POSITION

        if self._tilt_command_topic is not None:
            supported_features |= TILT_FEATURES

        return supported_features

    async def async_open_cover(self, **kwargs):
        """Move the cover up.

        This method is a coroutine.
        """
        mqtt.async_publish(
            self.hass, self._command_topic, self._payload_open, self._qos,
            self._retain)
        if self._optimistic:
            # Optimistically assume that cover has changed state.
            self._state = False
            if self._get_position_topic:
                self._position = self.find_percentage_in_range(
                    self._position_open, COVER_PAYLOAD)
            self.async_schedule_update_ha_state()

    async def async_close_cover(self, **kwargs):
        """Move the cover down.

        This method is a coroutine.
        """
        mqtt.async_publish(
            self.hass, self._command_topic, self._payload_close, self._qos,
            self._retain)
        if self._optimistic:
            # Optimistically assume that cover has changed state.
            self._state = True
            if self._get_position_topic:
                self._position = self.find_percentage_in_range(
                    self._position_closed, COVER_PAYLOAD)
            self.async_schedule_update_ha_state()

    async def async_stop_cover(self, **kwargs):
        """Stop the device.

        This method is a coroutine.
        """
        mqtt.async_publish(
            self.hass, self._command_topic, self._payload_stop, self._qos,
            self._retain)

    async def async_open_cover_tilt(self, **kwargs):
        """Tilt the cover open."""
        mqtt.async_publish(self.hass, self._tilt_command_topic,
                           self._tilt_open_position, self._qos,
                           self._retain)
        if self._tilt_optimistic:
            self._tilt_value = self._tilt_open_position
            self.async_schedule_update_ha_state()

    async def async_close_cover_tilt(self, **kwargs):
        """Tilt the cover closed."""
        mqtt.async_publish(self.hass, self._tilt_command_topic,
                           self._tilt_closed_position, self._qos,
                           self._retain)
        if self._tilt_optimistic:
            self._tilt_value = self._tilt_closed_position
            self.async_schedule_update_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        if ATTR_TILT_POSITION not in kwargs:
            return

        position = float(kwargs[ATTR_TILT_POSITION])

        # The position needs to be between min and max
        level = self.find_in_range_from_percent(position)

        mqtt.async_publish(self.hass, self._tilt_command_topic,
                           level, self._qos, self._retain)

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            position = kwargs[ATTR_POSITION]
            percentage_position = position
            if self._set_position_template is not None:
                try:
                    position = self._set_position_template.async_render(
                        **kwargs)
                except TemplateError as ex:
                    _LOGGER.error(ex)
                    self._state = None
            elif self._position_open != 100 and self._position_closed != 0:
                position = self.find_in_range_from_percent(
                    position, COVER_PAYLOAD)

            mqtt.async_publish(self.hass, self._set_position_topic,
                               position, self._qos, self._retain)
            if self._optimistic:
                self._state = percentage_position == self._position_closed
                self._position = percentage_position
                self.async_schedule_update_ha_state()

    def find_percentage_in_range(self, position, range_type=TILT_PAYLOAD):
        """Find the 0-100% value within the specified range."""
        # the range of motion as defined by the min max values
        if range_type == COVER_PAYLOAD:
            max_range = self._position_open
            min_range = self._position_closed
        else:
            max_range = self._tilt_max
            min_range = self._tilt_min
        current_range = max_range - min_range
        # offset to be zero based
        offset_position = position - min_range
        position_percentage = round(
            float(offset_position) / current_range * 100.0)

        max_percent = 100
        min_percent = 0
        position_percentage = min(max(position_percentage, min_percent),
                                  max_percent)
        if range_type == TILT_PAYLOAD and self._tilt_invert:
            return 100 - position_percentage
        return position_percentage

    def find_in_range_from_percent(self, percentage, range_type=TILT_PAYLOAD):
        """
        Find the adjusted value for 0-100% within the specified range.

        if the range is 80-180 and the percentage is 90
        this method would determine the value to send on the topic
        by offsetting the max and min, getting the percentage value and
        returning the offset
        """
        if range_type == COVER_PAYLOAD:
            max_range = self._position_open
            min_range = self._position_closed
        else:
            max_range = self._tilt_max
            min_range = self._tilt_min
        offset = min_range
        current_range = max_range - min_range
        position = round(current_range * (percentage / 100.0))
        position += offset

        if range_type == TILT_PAYLOAD and self._tilt_invert:
            position = max_range - position + offset
        return position

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._unique_id
