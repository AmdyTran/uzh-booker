# uzh-booker


## Setup
0. Make sure you have [uv installed](https://docs.astral.sh/uv/getting-started/installation/). 
1. Copy the `scheduler/.env.example` file to `./scheduler/.env` and replace the variables with your username and password. The TOTP code can be generated at `https://ubbooked01.ub.uzh.ch/ub/Web/profile.php`
2. Modify the `scheduler/config.py` file to your liking:
    - owner_id: go to create a new reservation page, open inspect element and lookup userId. Replace the value with your userId.
    - preferred_range_start and preferred_range_end: to find the range go into the software and try to make a reservation for your spot, you will see the link contains "?rid". Ensure your range is consecutive, best by finding spots within the same building.
    - preferred_start_time_hour, ...: the hour has to be GMT (so for CEST as of now shift down by 2 hours). Ensure these times are actually bookable, i.e. library is open.
    - standard_attribute_values: modify WWF with one of `"MeF", "MNF", "PhF", "RWF", "ThF", "VSF", "WWF", "ZDU"`


## Run with uv

Run the following command wihtin the folder where `pyproject.toml` is located
```sh
uv run book 
```

## Cron job example 
Create the following Cron job, to have the script automatically run on a schedule.

```
0-3 6 * * * PATH_TO_THIS_CURRENT_FOLDER/venv/bin/book >> ./tmp/uzh-booker.log 2>&1
```

Tip: Look at https://crontab.guru
The booking opens every day for the next week at 6 AM CEST, so adjust the cron job accordingly. 


