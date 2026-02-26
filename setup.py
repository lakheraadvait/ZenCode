from setuptools import setup, find_packages

setup(
    name="zencode",
    version="11.0.0",
    description="ZENCODE v11 — Autonomous AI Code Shell. More capable than Cursor.",
    long_description="""ZENCODE v11 features:
- Deep workspace intelligence: full file content, symbol index, git awareness, secret detection
- @file references in chat: type @app.py to inject any file into context
- .zenrules system: per-project AI instructions injected into all agents
- New agents: ResearchAgent (internet access), GitAgent (full git ops)
- New tools: web_search, git_command, grep_files, find_files, file_rename, file_copy
- Rich visual file tree with colors
- IDE completely removed — pure CLI power
- Multi-language: Python, JS/TS, Go, Rust, Ruby, PHP, Java, C/C++, C#, Lua, Swift, Dart
""",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "mistralai>=1.0.0",
        "rich>=13.7.0",
        "click>=8.1.0",
        "prompt_toolkit>=3.0.0",
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "zencode=zencode.CLI:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
