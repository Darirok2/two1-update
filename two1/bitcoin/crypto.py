import base58
import hashlib
import random

# Might want to switch these out with something generated by tinyber?
from pyasn1.type import univ, namedtype
from pyasn1.codec.der import encoder, decoder

from two1.bitcoin.utils import bytes_to_str
from two1.crypto.ecdsa import ECPointAffine, ECPointJacobian, EllipticCurve, secp256k1

bitcoin_curve = secp256k1()

class ECDERPoint(univ.Sequence):
    componentType = namedtype.NamedTypes(
        namedtype.NamedType("r", univ.Integer()),
        namedtype.NamedType("s", univ.Integer())
    )


def der_encode_point(pt):
    ''' Encodes an ECPointAffine using DER.

        Two components are encoded: r = pt.x and s = pt.y.

    Args:
        pt (ECPointAffine): The point to be encoded.

    Returns:
        dep (bytes): The DER encoding of pt.
    '''
    ep = ECDERPoint()
    ep.setComponentByName('r', pt.x)
    ep.setComponentByName('s', pt.y)

    return encoder.encode(ep)

def der_encode_hex(pt):
    ''' Returns a hex string of the result from der_encode_point()

    Args:
        pt (ECPointAffine): The point to be encoded.

    Returns:
        dep (str): DER encoded point as a hex string.
    '''
    enc = der_encode_point(pt)
    return bytes_to_str(enc)

def der_decode_point(curve, der):
    ''' Decodes an ECPoint that was DER-encoded.

    Args:
        curve (EllipticCurve): The curve the point is on.
        der (bytes): The DER encoding to be decoded.

    Returns:
        pt (ECPointAffine): The decoded point.
    '''
    if isinstance(der, bytes):
        d = decoder.decode(der)[0]
    elif isinstance(der, str):
        d = decoder.decode(bytes.fromhex(der))[0]
    else:
        raise TypeError("der must be either 'bytes' or 'str'")
    
    x = int(d.getComponentByPosition(0))
    y = int(d.getComponentByPosition(1))

    return ECPointAffine(curve, x, y)

class PrivateKey(object):
    TESTNET_VERSION = 0xEF
    MAINNET_VERSION = 0x80

    @staticmethod
    def from_int(i, testnet=False):
        return PrivateKey(i, testnet)

    @staticmethod
    def from_b58check(private_key):
        ''' Decodes a Base58Check encoded private-key.

        Args:
            private_key (str): A Base58Check encoded private key.

        Returns:
            pk (PrivateKey): A PrivateKey object
        '''
        b58dec = base58.b58decode_check(private_key)
        version = b58dec[0]
        assert version in [PrivateKey.TESTNET_VERSION, PrivateKey.MAINNET_VERSION]
        
        return PrivateKey(int.from_bytes(b58dec[1:], 'big'), version == PrivateKey.TESTNET_VERSION)

    @staticmethod
    def from_random(testnet=False):
        return PrivateKey(random.SystemRandom().randrange(1, bitcoin_curve.n - 1), testnet)

    def __init__(self, k, testnet=False):
        self.key = k
        self.version = self.TESTNET_VERSION if testnet else self.MAINNET_VERSION
        self._public_key = PublicKey.from_int(bitcoin_curve.public_key(self.key), testnet)

    @property
    def public_key(self):
        return self._public_key

    def raw_sign(self, message):
        ''' Signs message using this private key.

        Args:
            message (bytes): The message to be signed.

        Returns:
            pt (ECPointAffine): a raw point (r = pt.x, s = pt.y) which is the signature.
        '''
        return bitcoin_curve.sign(message, self.key)

    def sign(self, message):
        ''' Signs message using this private key.

        Note:
            This differs from `raw_sign()` since it returns a DER encoding
            of the signature point.

        Args:
            message (bytes): The message to be signed.

        Returns:
            pt (bytes): DER-encoded representation of the signature point.
        '''

        # Returns a DER encoded signature of message as a byte string.
        return der_encode_point(self.raw_sign(message))

    def to_b58check(self):
        return base58.b58encode_check(bytes(self))

    def to_hex(self):
        return bytes_to_str(bytes(self))

    def __bytes__(self):
        return bytes([self.version]) + self.key.to_bytes(32, 'big')

    def __int__(self):
        return self.key

    
class PublicKey(object):

    @staticmethod
    def from_point(p, testnet=False):
        return PublicKey(p.x, p.y, testnet)
    
    @staticmethod
    def from_int(i, testnet=False):
        point = ECPointAffine.from_int(bitcoin_curve, i)
        return PublicKey.from_point(point, testnet)
        
    @staticmethod
    def from_der(d, testnet=False):
        point = der_decode_point(bitcoin_curve, d)
        return PublicKey.from_point(point, testnet)

    @staticmethod
    def from_bytes(b, testnet=False):
        key_bytes_len = len(key_bytes)

        key_type = int(key[0:2])
        if key_type == 0x04:
            # Uncompressed
            assert key_bytes_len == 65
        
            x = int.from_bytes(key_bytes[1:32], 'big')
            y = int.from_bytes(key_bytes[32:65], 'big')
        elif key_type == 0x02 or key_type == 0x03:
            assert key_bytes_len == 33
            x = int.from_bytes(key_bytes[1:32], 'big')
            y = bitcoin_curve.y_from_x(x)
            if y % 2 != (key_type - 2):
                y = -y % bitcoin_curve.p
        else:
            return None

        return PublicKey(x, y, testnet)

    @staticmethod
    def from_hex(h, testnet=False):
        return PublicKey.from_bytes(bytes.fromhex(h), testnet)

    @staticmethod
    def from_private_key(private_key):
        return private_key.public_key
    
    def __init__(self, x, y, testnet=False):
        p = ECPointAffine(bitcoin_curve, x, y)
        assert bitcoin_curve.is_on_curve(p)

        self.point = p
        self.testnet = testnet

        pk_sha = hashlib.sha256(bytes(self)).digest()
    
        # RIPEMD-160 of SHA-256
        r = hashlib.new('ripemd160')
        r.update(pk_sha)
        ripe = r.digest()

        # Put the version byte in front, 0x00 for Mainnet, 0x6F for testnet
        version = bytes([0x6F]) if self.testnet else bytes([0x00])

        self._address = version + ripe
        self._b58address = base58.b58encode_check(self._address)

    @property
    def address(self):
        return self._address
        
    @property
    def b58address(self):
        return self._b58address

    def verify(self, message, signature):
        ''' Verifies that message was appropriately signed.

        Args:
            message (bytes): The message to be verified.
            signature (bytes or str): A DER-encoded signature.

        Returns:
            verified (bool): True if the signature is verified, False otherwise.
        '''
        if isinstance(signature, bytes):
            sig = signature
        elif isinstance(signature, str):
            sig = bytes.fromhex(signature)
        else:
            raise TypeError("signature must be either 'bytes' or 'str'!")
        
        sig_pt = der_decode_point(bitcoin_curve, sig)
    
        return bitcoin_curve.verify(message, sig_pt, self.point)
    
    def to_der(self):
        return der_encode_point(self.point)

    def to_hex(self):
        return bytes_to_str(bytes(self))

    def __int__(self):
        return (self.point.x << bitcoin_curve.n.bit_length()) + self.point.y
        
    def __bytes__(self):
        return bytes([0x04]) + self.point.x.to_bytes(32, 'big') + self.point.y.to_bytes(32, 'big')


if __name__ == "__main__":
    private_key = PrivateKey.from_random()
    public_key = private_key.public_key

    pk_hex = private_key.to_hex()
    print("private key = %s, len = %d" % (pk_hex, len(pk_hex)))
    print("public key = %s" % public_key.to_hex())
    print("public key address = %s" % public_key.b58address)
    
    message = b"foobar"
    sig = private_key.sign(message)
    sig_hex = bytes_to_str(sig)
    print("signature = %s" % sig_hex)
    sig_ver = public_key.verify(message, sig)
    print("signature verified: %r" % (sig_ver))

