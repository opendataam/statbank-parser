from setuptools import setup, find_packages

setup(
    name='statbank-parser',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'requests',
        'beautifulsoup4',
        'click',
        'pandas',
        'lxml',
        'openpyxl',
    ],
    entry_points={
        'console_scripts': [
            'statbank-parser=statbank_parser.cli:cli',
        ],
    },
)
