import argparse
import traceback
from datetime import timedelta
from config_manager import read_config, config
from common import logger, TerminateProcessException, ConfigReaderException, current_utc_time, time_elapsed_since, sleep, time_remaining_till_target_time, gps_seconds_to_datetime, utc_to_local_time
from multicast_configurator import configure_multicast_group, setup_and_start_multicast_session, enqueue_multicast_command, clean_up
from mqtt_client import subscribe_uplink, unsubscribe_uplink

if __name__ == "__main__":
    start_time = current_utc_time()
    mqtt_client = None
    try:
        # Init - Read Configuration
        parser = argparse.ArgumentParser(description="Configure LoRaWAN multicast.")
        parser.add_argument("--config", type=str, default="config.ini", help="Path to the configuration file.")
        args = parser.parse_args()
        read_config(args.config)
        
        # Step 1 - subscribe to device uplinks
        subscribe_uplink()

        # Step 2 - create and configure multicast group
        mc_group_json = configure_multicast_group()

        # Step 3 - setup and start multicast session
        setup_and_start_multicast_session()
        logger.info("Multicast configuration and session setup completed successfully.")

        # Step 4 - wait till rendezvous time
        mc_offset = config['multicast_window_offset_seconds'] # Additional offset seconds to ensure device is ready and listening to multicast
        rendezvous_time = gps_seconds_to_datetime(mc_group_json.get('session_time')) + timedelta(seconds=mc_offset)
        rendezvous_time_local_tz = utc_to_local_time(utc_time=rendezvous_time)
        logger.info(f"Waiting till Rendezvous Time (+{mc_offset}s offset): {rendezvous_time_local_tz} ({rendezvous_time.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        while current_utc_time() < rendezvous_time:
            print(f"Time remaining till rendezvous: {time_remaining_till_target_time(rendezvous_time)}", end='\r')
            sleep(seconds=1)
        logger.info("=========== Class C session started. Ready to receive multicast commands! ===========")

        # Step 5 - enqueue user commands
        # enqueue_multicast_command() # TODO - enable to test multicast commands to devices
        
        # Step 6 - wait and monitor
        logger.info("Monitor and tryout multicast commands from ChirpStack!")
        session_timeout = rendezvous_time + timedelta(seconds=(2**config['session_timeout_exponent'])-mc_offset)
        session_timeout_local_tz = utc_to_local_time(session_timeout)
        logger.info(f"Waiting till Class C session timeout (-{mc_offset}s offset): {session_timeout_local_tz} ({session_timeout.strftime('%Y-%m-%d %H:%M:%S')} UTC)")
        while current_utc_time() < session_timeout:
            print(f"Time remaining till Class C session timeout: {time_remaining_till_target_time(session_timeout)}", end='\r')
            sleep(seconds=1)
        
        logger.info("=========== Class C session timeout reached ===========")
    except ConfigReaderException as err:
        logger.critical(err)
        logger.debug(f"{traceback.format_exc()}")
        config.clear()  # Ensure config is empty to skip cleanup and summary
    except TerminateProcessException as err:
        logger.critical(err)
        logger.debug(f"{traceback.format_exc()}")
    except Exception as err:
        logger.critical(f"Oops! Error: {err}")
        logger.debug(f"{traceback.format_exc()}")
    except KeyboardInterrupt as err:
        logger.critical("Program terminated by user, Exiting gracefully...")
    finally:
        try:
            if config != {}:
                # Clean up
                if config['delete_mc_group_on_exit']:
                    try:
                        clean_up() # Delete multicast group from ChirpStack
                    except Exception as err:
                        logger.error(f"Error during multicast group clean up: {err}")
                        logger.debug(f"{traceback.format_exc()}")
                else:
                    logger.info("Skipped multicast group clean up as delete_mc_group_on_exit=false")
                
                # Stop MQTT loop and disconnect
                unsubscribe_uplink()

                # Print summary
                logger.info("Multicast status summary:")
                logger.info("Gateways:")
                for gw_id in config['gateway_id_multicast_status_tracker']:
                    logger.info(f"  {gw_id}: {config['gateway_id_multicast_status_tracker'][gw_id]}")
                logger.info("Devices:")
                for dev_eui in config['dev_eui_multicast_status_tracker']:
                    logger.info(f"  {dev_eui}: {config['dev_eui_multicast_status_tracker'][dev_eui]}")
                
                logger.info(f"Total execution time: {time_elapsed_since(start_time)}")
                logger.info("Execution stopped, Exiting...")
                input("\nPress Enter to exit...")
        except TerminateProcessException as err:
            logger.critical(err)
            logger.debug(f"{traceback.format_exc()}")
        except Exception as err:
            logger.critical(f"Oops! Error: {err}")
            logger.debug(f"{traceback.format_exc()}")
        except KeyboardInterrupt as err:
            logger.critical("Program terminated by user forcefully during cleanup, Some resources might not have been released properly.")