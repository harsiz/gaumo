from setuptools import setup, find_packages

setup(
    name='gaumo',
    version='0.1.0',
    description='Gaumo (GAU) - A modular Python cryptocurrency',
    packages=find_packages(),
    python_requires='>=3.9',
    install_requires=[
        'ecdsa>=0.18.0',
        'websockets>=11.0',
        'aiohttp>=3.9.0',
    ],
    entry_points={
        'console_scripts': [
            'gaumo=gaumo.cli.cli:main',
        ],
    },
)
