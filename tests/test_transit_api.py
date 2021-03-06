  #!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Transit-Secrets-Engine-like API test module."""

import base64
import os
import sys
import time
import unittest
import uuid

from hvac.exceptions import (
  InvalidPath,
  InvalidRequest,
  ParamValidationError
)

from hvac_openpgp import Client
from hvac_openpgp.constants import (
  ALLOWED_HASH_DATA_ALGORITHMS,
  ALLOWED_KEY_TYPES,
  ALLOWED_MARSHALING_ALGORITHMS,
  ALLOWED_SIGNATURE_ALGORITHMS,
)
from hvac_openpgp.exceptions import UnsupportedParam

class TestOpenPGP(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    # Useful test constants.
    cls.EXPORTABLE = (None, False, True)

    # The only part of the API we care about.
    client = Client(os.environ['VAULT_ADDR'], os.environ['VAULT_TOKEN'])
    cls.openpgp = client.secrets.openpgp

  def tearDown(self):
    try:
      r1 = self.openpgp.list_keys()
    except InvalidPath:
      pass
    else:
      # https://github.com/hashicorp/vault/blob/00494efd12bd7f762c38856ab83b69d8eeb8d1ac/sdk/logical/response.go#L131
      for name in r1['data']['keys']:
        r2 = self.openpgp.delete_key(name)
        r2.raise_for_status()

  def random_name(self):
    return str(uuid.uuid4())

  def test_1_list_keys(self):
    # List keys when there are none.
    # TODO: Should this raise an exception in the first place?
    with self.assertRaises(InvalidPath, msg='Listed keys when there are none!'):
      self.openpgp.list_keys()

    # Create and list keys.
    keys = []
    for key_type in ALLOWED_KEY_TYPES:
      name = self.random_name()
      self.openpgp.create_key(name, key_type=key_type)
      keys.append(name)

    r = self.openpgp.list_keys()
    # https://github.com/hashicorp/vault/blob/00494efd12bd7f762c38856ab83b69d8eeb8d1ac/sdk/logical/response.go#L131
    assert sorted(r['data']['keys']) == sorted(keys)

  def test_2_read_key(self):
      # Read nonexistent key.
      with self.assertRaises(InvalidRequest, msg='Read nonexistent key!'):
        self.openpgp.read_key(self.random_name())

  def test_3_create_read_and_delete_key(self):
    # Unsupported parameters.
    unsupported_parameters = (
      {'allow_plaintext_backup': True},
      {'convergent_encryption': True},
      {'derived': True},
    )
    for parameter in unsupported_parameters:
      with self.assertRaises(UnsupportedParam,
                             msg=f'Unsupported parameter: {parameter}!'):
        self.openpgp.create_key(self.random_name(), **parameter)

    # By default, RSA-4096 keys are created.
    # TODO: test that it is indeed RSA-4096!
    self.openpgp.create_key(self.random_name())

    # Allowed key types, exportable values, real names, and email addresses.
    for key_type in ALLOWED_KEY_TYPES:
      for exportable in self.EXPORTABLE:
        for real_name in (None, 'John Doe'):
          for email in (None, 'john.doe@datadoghq.com'):
            fixed_name = self.random_name()
            r = self.openpgp.create_key(fixed_name,
                                        key_type=key_type,
                                        exportable=exportable,
                                        real_name=real_name,
                                        email=email)
            r.raise_for_status()

            r = self.openpgp.read_key(fixed_name)
            data = r['data']

            # Public information.
            self.assertIn('fingerprint', data)
            self.assertIn('public_key', data)
            self.assertIn('exportable', data)

            # Private information.
            self.assertNotIn('name', data)
            self.assertNotIn('key', data)

            # Delete.
            r = self.openpgp.delete_key(fixed_name)
            r.raise_for_status()

    # Duplicate keys.
    fixed_name = self.random_name()
    self.openpgp.create_key(fixed_name)
    # https://github.com/trishankatdatadog/vault-gpg-plugin/pull/5
    with self.assertRaises(InvalidRequest, msg='Duplicate key created!'):
      self.openpgp.create_key(fixed_name)

  # https://hvac.readthedocs.io/en/stable/usage/secrets_engines/transit.html#sign-data
  def base64ify(self, bytes_or_str):
      """Helper method to perform base64 encoding across Python 2.7 and Python 3.X"""

      if sys.version_info[0] >= 3 and isinstance(bytes_or_str, str):
          input_bytes = bytes_or_str.encode('utf8')
      else:
          input_bytes = bytes_or_str

      output_bytes = base64.urlsafe_b64encode(input_bytes)
      if sys.version_info[0] >= 3:
          return output_bytes.decode('ascii')
      else:
          return output_bytes

  def test_4_sign_and_verify_data(self):
    fixed_input = 'Hello, world!'
    base64_input = self.base64ify(fixed_input)
    base64_bad_input = self.base64ify(fixed_input+'!!')

    for key_type in ALLOWED_KEY_TYPES:
      fixed_name = self.random_name()

      # Sign w/o creating.
      with self.assertRaises(InvalidRequest,
                             msg=f'Nonexistent key: {fixed_name}!'):
        self.openpgp.sign_data(fixed_name, base64_input)

      # Verify w/o creating.
      with self.assertRaises(InvalidRequest,
                             msg=f'Nonexistent key: {fixed_name}!'):
        self.openpgp.verify_signed_data(fixed_name, base64_input, signature='')

      # Create key.
      self.openpgp.create_key(fixed_name, key_type=key_type)

      # Unsupported parameters for signing.
      unsupported_parameters = (
        {'key_version': 2},
        {'context': ''},
        {'prehashed': True},
      )
      for parameter in unsupported_parameters:
        with self.assertRaises(UnsupportedParam,
                              msg=f'Unsupported parameter: {parameter}!'):
          self.openpgp.sign_data(fixed_name, base64_input, **parameter)

      # Unsupported parameters for verification.
      unsupported_parameters = (
        {'context': ''},
        {'hmac': ''},
        {'prehashed': True},
      )
      for parameter in unsupported_parameters:
        with self.assertRaises(UnsupportedParam,
                              msg=f'Unsupported parameter: {parameter}!'):
          self.openpgp.verify_signed_data(fixed_name, base64_input,
                                          signature='', **parameter)

      # Not base64 hash input for signing.
      with self.assertRaises(InvalidRequest, msg='Not base64 hash input!'):
        self.openpgp.sign_data(fixed_name, fixed_input)

      # Not base64 hash input for verification.
      with self.assertRaises(InvalidRequest, msg='Not base64 hash input!'):
        self.openpgp.verify_signed_data(fixed_name, fixed_input, signature='')

      # All supported as well as empty hash, marshaling, and signature algorithms.
      for hash_algorithm in ALLOWED_HASH_DATA_ALGORITHMS | {None}:
        for marshaling_algorithm in ALLOWED_MARSHALING_ALGORITHMS | {None}:
          for signature_algorithm in ALLOWED_SIGNATURE_ALGORITHMS | {None}:
            # Make a signature.
            r = self.openpgp.sign_data(fixed_name, base64_input,
                                       hash_algorithm=hash_algorithm,
                                       marshaling_algorithm=marshaling_algorithm,
                                       signature_algorithm=signature_algorithm)
            signature = r['data']['signature']

            # Forget to pass signature for verification.
            with self.assertRaises(ParamValidationError, msg='No "signature"!'):
              self.openpgp.verify_signed_data(fixed_name, base64_input,
                                                hash_algorithm=hash_algorithm,
                                                marshaling_algorithm=marshaling_algorithm,
                                                signature_algorithm=signature_algorithm)

            # Original input.
            r = self.openpgp.verify_signed_data(fixed_name, base64_input,
                                                hash_algorithm=hash_algorithm,
                                                marshaling_algorithm=marshaling_algorithm,
                                                signature=signature,
                                                signature_algorithm=signature_algorithm)
            self.assertTrue(r['data']['valid'])

            # Bad input.
            r = self.openpgp.verify_signed_data(fixed_name, base64_bad_input,
                                                hash_algorithm=hash_algorithm,
                                                marshaling_algorithm=marshaling_algorithm,
                                                signature=signature,
                                                signature_algorithm=signature_algorithm)
            self.assertFalse(r['data']['valid'])

            # Bad signature.
            mid_len = len(signature) // 2
            bad_signature = signature[:mid_len] + '!!' + signature[mid_len:]
            r = self.openpgp.verify_signed_data(fixed_name, base64_input,
                                                hash_algorithm=hash_algorithm,
                                                marshaling_algorithm=marshaling_algorithm,
                                                signature=bad_signature,
                                                signature_algorithm=signature_algorithm)
            self.assertFalse(r['data']['valid'])

            # TODO: pass in mismatching hashing/marshaling algorithm.

      # Test default hashing/marshaling algorithms.
      r = self.openpgp.sign_data(fixed_name, base64_input)
      signature = r['data']['signature']
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=signature)
      self.assertTrue(r['data']['valid'])

  def test_5_delete_key(self):
      # Deleting a nonexistent key does not raise an exception.
      # TODO: inconsistent behaviour compared to list/read keys.
      r = self.openpgp.delete_key(self.random_name())
      r.raise_for_status()

  def test_6_export_key(self):
    # Export nonexistent key.
    # TODO: Should this raise an exception in the first place?
    with self.assertRaises(InvalidPath, msg='Exported nonexistent key!'):
      self.openpgp.export_key(self.random_name())

    # Export key not marked as exportable.
    nonexportable = self.random_name()
    self.openpgp.create_key(nonexportable)
    with self.assertRaises(InvalidRequest, msg='Exported nonexportable key!'):
      self.openpgp.export_key(nonexportable)

    # Export key marked as exportable.
    exportable = self.random_name()
    self.openpgp.create_key(exportable, exportable=True)

    with self.assertRaises(UnsupportedParam,
                           msg=f'Unsupported parameter: version!'):
      self.openpgp.export_key(exportable, version=2)

    r = self.openpgp.export_key(exportable)
    data = r['data']

    # Public information.
    self.assertNotIn('fingerprint', data)
    self.assertNotIn('public_key', data)
    self.assertNotIn('exportable', data)

    # Private information.
    self.assertIn('name', data)
    self.assertIn('key', data)

    # Key type has no effect.
    re = self.openpgp.export_key(exportable, key_type='encryption-key')
    rs = self.openpgp.export_key(exportable, key_type='signing-key')
    self.assertDictEqual(re['data'], rs['data'])

  def test_7_crud_subkeys(self):
    fixed_name = self.random_name()
    fixed_input = 'Hello, world!'
    base64_input = self.base64ify(fixed_input)

    self.openpgp.create_key(fixed_name)
    self.openpgp.read_key(fixed_name)

    r = self.openpgp.create_subkey(fixed_name)
    key_id = r['data']['key_id']

    self.openpgp.read_subkey(fixed_name, key_id)

    r = self.openpgp.list_subkeys(fixed_name)
    # https://github.com/hashicorp/vault/blob/00494efd12bd7f762c38856ab83b69d8eeb8d1ac/sdk/logical/response.go#L131
    key_ids = r['data']['keys']
    self.assertIn(key_id, key_ids)

    r = self.openpgp.sign_data(fixed_name, base64_input)
    s = r['data']['signature']
    r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
    self.assertTrue(r['data']['valid'])

    r = self.openpgp.delete_subkey(fixed_name, key_id)
    r.raise_for_status()

    r = self.openpgp.list_subkeys(fixed_name)
    # https://github.com/hashicorp/vault/blob/00494efd12bd7f762c38856ab83b69d8eeb8d1ac/sdk/logical/response.go#L131
    key_ids = r['data']['keys']
    self.assertNotIn(key_id, key_ids)

    r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
    self.assertFalse(r['data']['valid'])

  def test_8_signing_with_subkeys(self):
    SIG_EXPIRES_SECS = 10
    KEY_EXPIRES_SECS = 2 * SIG_EXPIRES_SECS
    fixed_input = 'Hello, world!'
    base64_input = self.base64ify(fixed_input)

    for key_type in ALLOWED_KEY_TYPES:
      fixed_name = self.random_name()

      # Create an expiring signing subkey.
      self.openpgp.create_key(fixed_name, key_type=key_type)
      self.openpgp.create_subkey(fixed_name, key_type=key_type, expires=KEY_EXPIRES_SECS)

      # Test expiring signatures.
      r = self.openpgp.sign_data(fixed_name, base64_input, expires=SIG_EXPIRES_SECS)
      s = r['data']['signature']
      # Before expiry.
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertTrue(r['data']['valid'])
      # Sleep until signature expires.
      time.sleep(SIG_EXPIRES_SECS)
      # After expiry.
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertFalse(r['data']['valid'])

      # Test key expiration.
      r = self.openpgp.sign_data(fixed_name, base64_input)
      s = r['data']['signature']
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertTrue(r['data']['valid'])
      # Sleep until key expires.
      time.sleep(KEY_EXPIRES_SECS)
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertFalse(r['data']['valid'])

  def test_9_expiring_master_keys(self):
    KEY_EXPIRES_SECS = 20
    fixed_input = 'Hello, world!'
    base64_input = self.base64ify(fixed_input)

    for key_type in ALLOWED_KEY_TYPES:
      fixed_name = self.random_name()

      # Create an expiring signing subkey.
      self.openpgp.create_key(fixed_name, key_type=key_type, expires=KEY_EXPIRES_SECS)

      # Test key expiration.
      r = self.openpgp.sign_data(fixed_name, base64_input)
      s = r['data']['signature']
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertTrue(r['data']['valid'])
      # Sleep until key expires.
      time.sleep(KEY_EXPIRES_SECS)
      r = self.openpgp.verify_signed_data(fixed_name, base64_input, signature=s)
      self.assertFalse(r['data']['valid'])

if __name__ == '__main__':
  unittest.main()