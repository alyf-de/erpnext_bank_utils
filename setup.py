# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

# get version from __version__ variable in erpnext_bank_utils/__init__.py
from erpnext_bank_utils import __version__ as version

setup(
	name='erpnext_bank_utils',
	version=version,
	description='ERPNext Bank Utils',
	author='ALYF GmbH',
	author_email='hallo@alyf.de',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
