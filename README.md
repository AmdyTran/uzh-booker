# UZH Booking System

An sync booking system for the University of Zurich (UZH) resource reservation system. Features a competitive "spam booking" strategy designed to maximize success rates in high-demand booking scenarios.

## 🛠️ Installation

```bash
# Clone the repository
git clone <repository-url>
cd uzh-booker

# Install dependencies
uv sync

# Set up environment variables
cp scheduler/.env.example scheduler/.env
# Edit .env with your credentials
```

## ⚙️ Configuration

Create `scheduler/.env` with your UZH credentials:

```env
UZH_USERNAME=your_username
UZH_PASSWORD=your_password
UZH_TOTP_SECRET=your_totp_secret
```

### Configuration Options

Edit `scheduler/config.py` to customize:

- **Booking time**: `preferred_start_time_hour/minute`, `preferred_end_time_hour/minute`
- **Resource range**: `preferred_range_start`, `preferred_range_end`
- **Owner ID**: `owner_id`
- **Attributes**: `standard_attribute_values`

## 🎯 Usage

### Quick Start

```bash
# Run async booking (recommended)
uv run book-async
```

### Available Commands

```bash
# Booking commands
uv run book-async          # Async spam booking (recommended)
uv run book                # Legacy synchronous booking
uv run refresh-async       # Refresh authentication session

# Demo and utilities
uv run record-cassettes    # Record VCR test cassettes

# Development
uv run pytest             # Run tests
uv run ruff format .       # Format code
uv run ruff check .        # Lint code
```

## 🧪 Testing

The project uses VCR (Video Cassette Recorder) to record real HTTP interactions and replay them in tests.

### Running Tests

```bash
# Run all tests (uses recorded cassettes)
uv run pytest tests/ -v

# Run replay tests (offline, uses cassettes)
uv run pytest tests/ -v -m "not live"
```

### Recording New Cassettes

**One-time setup** - Records real API interactions:

```bash
# Option 1: Use the recording script
uv run record-cassettes

# Option 2: Run recording tests directly
uv run pytest tests/ -m live -v
```

**Requirements for recording**:
- Valid UZH credentials in `.env` file
- Network access to UZH booking system
- Run during booking hours

### Test Structure

- **Recording tests** (`-m live`): Make real API calls to record interactions
- **Replay tests** (default): Use recorded data for fast, consistent testing
- **Utility tests**: Test pure functions without HTTP calls

### What Gets Recorded

The cassettes contain **real API responses**:
- ✅ Actual success/failure results
- ✅ Real error messages ("Es ist nur eine Reservierung zur selben Zeit möglich")
- ✅ Genuine booking reference numbers
- ✅ Authentic response timing
- 🔒 Sensitive data filtered out (credentials, CSRF tokens)

## 🔧 Development

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Type checking
uv run mypy scheduler/

# Run all quality checks
uv run ruff format . && uv run ruff check . && uv run pytest
```

### Adding New Features

1. **Extend BookingRequest/BookingResult** for new data
2. **Add utility functions** to the appropriate sections
3. **Update tests** with new VCR recordings if needed
