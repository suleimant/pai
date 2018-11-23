import sys
import inspect
import logging
from construct import *
from .common import calculate_checksum, ProductIdEnum, CommunicationSourceIDEnum

logger = logging.getLogger('PAI').getChild(__name__)


class Panel:
    mem_map = {}

    def __init__(self, core, product_id):
        self.core = core
        self.product_id = product_id

    def parse_message(self, message):
        if message is None or len(message) == 0:
            return None

        if message[0] == 0x72 and message[1] == 0:
            return InitiateCommunication.parse(message)
        elif message[0] == 0x72 and message[1] == 0xFF:
            return InitiateCommunicationResponse.parse(message)
        elif message[0] == 0x5F:
            return StartCommunication.parse(message)
        elif message[0] == 0x00 and message[4] > 0:
            return StartCommunicationResponse.parse(message)
        else:
            logger.error("Unknown message: %s" % (" ".join("{:02x} ".format(c) for c in message)))
            return None

    def get_message(self, name):
        clsmembers = dict(inspect.getmembers(sys.modules[__name__]))
        if name in clsmembers:
            return clsmembers[name]
        else:
            raise ResourceWarning('{} parser not found'.format(name))

    def encode_password(self, password):
        res = [0] * 5

        if password is None:
            return b'\x00\x00'

        try:
            int_password = int(password)
        except:
            return password

        i = len(password)
        while i >= 0:
            i2 = int(i / 2)
            b = int(int_password % 10)
            if b == 0:
                b = 0x0a

            int_password /= 10
            if (i + 1) % 2 == 0:
                res[i2] = b
            else:
                res[i2] = (((b << 4)) | res[i2]) & 0xff

            i -= 1

        return bytes(res[:2])

    def update_labels(self):
        logger.info("Updating Labels from Panel")

        output_template = dict(
            on=False,
            pulse=False)

        eeprom_zone_addresses = range(self.mem_map['zone']['start'], self.mem_map['zone']['end'], self.core_mem_map['zone']['size'])
        self.load_labels(self.core.zones, self.core.labels['zone'], eeprom_zone_addresses)
        logger.info("Zones: {}".format(', '.join(self.core.labels['zone'])))

        eeprom_partition_addresses = range(self.mem_map['partition']['start'], self.mem_map['partition']['end'], self.core_mem_map['partition']['size'])
        self.load_labels(self.core.partitions, self.core.labels['partition'], eeprom_partition_addresses)
        logger.info("Partitions: {}".format(', '.join(list(self.core.labels['partition']))))

        eeprom_output_addresses = range(self.mem_map['output']['start'], self.mem_map['output']['end'], self.core_mem_map['output']['size'])
        self.load_labels(self.core.outputs, self.core.labels['output'], eeprom_output_addresses, template=output_template)
        logger.info("Output: {}".format(', '.join(self.core.labels['output'])))

        eeprom_user_addresses = range(self.mem_map['user']['start'], self.mem_map['user']['end'], self.core_mem_map['user']['size'])
        self.load_labels(self.core.users, self.core.labels['user'], eeprom_user_addresses)
        logger.info("Users: {}".format(', '.join(list(self.core.labels['user']))))

    def load_labels(self,
                    labelDictIndex,
                    labelDictName,
                    addresses,
                    field_length=16,
                    template=dict(label='')):
        """Load labels from panel"""
        i = 1

        for address in addresses:
            args = dict(address=address, length=field_length)
            reply = self.core.send_wait(self.get_message('ReadEEPROM'), args, reply_expected=0x05)

            retry_count = 3
            for retry in range(1, retry_count + 1):
                # Avoid errors due to collision with events. It should not come here as we use reply_expected=0x05
                if reply is None:
                    logger.error("Could not fully load labels")
                    return

                if reply.fields.value.address != address:
                    logger.debug(
                        "Fetched and receive label EEPROM addresses (received: %d, requested: %d) do not match. Retrying %d of %d" % (
                            reply.fields.value.address, address, retry, retry_count))
                    reply = self.core.send_wait(None, None, reply_expected=0x05)
                    continue

                if retry == retry_count:
                    logger.error('Failed to fetch label at address: %d' % address)

                break

            data = reply.fields.value.data
            label = data.strip(b'\0 ').replace(b'\0', b'_').replace(b' ', b'_').decode('utf-8')

            if label not in labelDictName:
                properties = template.copy()
                properties['label'] = label
                labelDictIndex[i] = properties

                labelDictName[label] = i
            i += 1

InitiateCommunication = Struct("fields" / RawCopy(
    Struct("po" / BitStruct(
        "command" / Const(7, Nibble),
        "reserved0" / Const(2, Nibble)),
           "reserved1" / Padding(35))),
                               "checksum" / Checksum(Bytes(1),
                                                     lambda data: calculate_checksum(data), this.fields.data))

InitiateCommunicationResponse = Struct("fields" / RawCopy(
    Struct(
        "po" / BitStruct(
            "command" / Const(7, Nibble),
            "message_center" / Nibble
        ),
        "new_protocol" / Const(0xFF, Int8ub),
        "protocol_id" / Int8ub,
        "protocol" / Struct(
            "version" / Int8ub,
            "revision" / Int8ub,
            "build" / Int8ub
        ),
        "family_id" / Int8ub,
        "product_id" / ProductIdEnum,
        "talker" / Enum(Int8ub,
                        BOOT_LOADER=0,
                        CONTROLLER_APPLICATION=1,
                        MODULE_APPLICATION=2),
        "application" / Struct(
            "version" / Int8ub,
            "revision" / Int8ub,
            "build" / Int8ub),
        "serial_number" / Bytes(4),
        "hardware" / Struct(
            "version" / Int8ub,
            "revision" / Int8ub),
        "bootloader" / Struct(
            "version" / Int8ub,
            "revision" / Int8ub,
            "build" / Int8ub,
            "day" / Int8ub,
            "month" / Int8ub,
            "year" / Int8ub),
        "processor_id" / Int8ub,
        "encryption_id" / Int8ub,
        "reserved0" / Bytes(2),
        "label" / Bytes(8))),

                                       "checksum" / Checksum(
                                           Bytes(1),
                                           lambda data: calculate_checksum(data), this.fields.data))

StartCommunication = Struct("fields" / RawCopy(
    Struct(
        "po" / Struct("command" / Const(0x5F, Int8ub)),
        "validation" / Const(0x20, Int8ub),
        "not_used0" / Padding(31),
        "source_id" / Default(CommunicationSourceIDEnum, 1),
        "user_id" / Struct(
            "high" / Default(Int8ub, 0),
            "low" / Default(Int8ub, 0)),
    )), "checksum" / Checksum(
    Bytes(1), lambda data: calculate_checksum(data), this.fields.data))

StartCommunicationResponse = Struct("fields" / RawCopy(
    Struct(
        "po" / BitStruct("command" / Const(0, Nibble),
                         "status" / Struct(
                             "reserved" / Flag,
                             "alarm_reporting_pending" / Flag,
                             "Windload_connected" / Flag,
                             "NeWare_connected" / Flag)
                         ),
        "not_used0" / Bytes(3),
        "product_id" / ProductIdEnum,
        "firmware" / Struct(
            "version" / Int8ub,
            "revision" / Int8ub,
            "build" / Int8ub),
        "panel_id" / Int16ub,
        "not_used1" / Bytes(5),
        "transceiver" / Struct(
            "firmware_build" / Int8ub,
            "family" / Int8ub,
            "firmware_version" / Int8ub,
            "firmware_revision" / Int8ub,
            "noise_floor_level" / Int8ub,
            "status" / BitStruct(
                "not_used" / BitsInteger(6),
                "noise_floor_high" / Flag,
                "constant_carrier" / Flag,
            ),
            "hardware_revision" / Int8ub,
        ),
        "not_used2" / Bytes(14),
    )),
                                    "checksum" / Checksum(
                                        Bytes(1), lambda data: calculate_checksum(data), this.fields.data))
