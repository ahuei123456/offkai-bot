# What is Offkai Bot?

A bot designed to simplify the process of attendance gathering for big gatherings. Our current usecase is mainly for large group dinners after lives/concerts/other events, so thus the name "Offkai Bot".

This bot is aimed to replace the previous manual methods of collating attendance for offkais, including and not limited to Google Forms surveys, collecting reactions on a Discord message, and waiting for replies of "I'm attending". Previous challenges faced have included errors in keeping track of attendees and attendees not receiving updates for various reasons, which this bot hopes to solve.

## Commands

Anyone who is interested in organizing an offkai using the slash commands must have the `Offkai Organizer` role in the server.

### create_offkai

- `event_name`: Name of the event to create (e.g. Hasu 4L Yokohama D2)
- `venue`: Name of the venue of the offkai (e.g. Yokohama Chibachan)
- `address`: Address of the venue (e.g. 〒220-0004 Kanagawa, Yokohama, Nishi Ward, Kitasaiwai, 1 Chome−8−2 犬山西口ビル 7階)
- `google_maps_link`: A link to the Google Maps page of the venue (e.g. https://maps.app.goo.gl/sa8k1VzNBr4CsiLy6)
- `date_time`: The date and time of the offkai, in YYYY-MM-DD HH:MM format (e.g. 2025-06-08 21:00)
- `announce_msg`: A message to accompany the announcement.

Creates a new thread in the current channel with the details of the offkai. The message will also include buttons to confirm attendance (if registration is still open) and to show how many attendees there are for the event.

### modify_offkai

- `event_name`: Name of the event to modify (e.g. Hasu 4L Yokohama D2)
- `venue`: Name of the new venue of the offkai (e.g. Yokohama Chibachan)
- `address`: Address of the mew venue (e.g. 〒220-0004 Kanagawa, Yokohama, Nishi Ward, Kitasaiwai, 1 Chome−8−2 犬山西口ビル 7階)
- `google_maps_link`: A new link to the Google Maps page of the venue (e.g. https://maps.app.goo.gl/sa8k1VzNBr4CsiLy6)
- `date_time`: The new date and time of the offkai, in YYYY-MM-DD HH:MM format (e.g. 2025-06-08 21:00)
- `update_msg`: A message to accompany the modification announcement.

Modifies an existing offkai with a new venue, address, Google Maps link and Date/Time.

### close_offkai

- `event_name`: Name of the event to close (autocompletes from existing events)

Closes responses for an offkai and sends a message in the current channel that responses have been closed. The response button is disabled, but users may still check the attendance count for the total number of people.

**TO-DO**: Allow specifying custom messages for the announcement.\
**TO-DO**: Send an error message if the offkai is already closed.

### reopen_offkai

- `event_name`: Name of the event to close (autocompletes from existing events)

Reopens responses for an offkai and sends a message in the current channel that responses have been reopened. The response button is reenabled until it is closed again.

**TO-DO**: Allow specifying custom messages for the announcement.\
**TO-DO**: Send an error message if the offkai is already reopened.

### archive_offkai

- `event_name`: Name of the event to archive (autocompletes from existing events)

Archives an offkai and no longer shows it in the autocomplete list.

### broadcast

- `event_name`: Name of the event to broadcast to (autocompletes from existing events)
- `message`: Message to send 

Broadcasts a message in the thread that was opened for the offkai.

**TO-DO**: Add an URGENT flag to also DM the announcement to offkai participants.

### attendance

- `event_name`: Name of the event to get the attendance list for (autocompletes from existing events)

Sends an ephemeral message with a count of the total number of attendees, and a list of their Discord usernames at the time of response, including all their associated +1s and +2s and so on. 

## User Response Form

Clicking on the `Confirm Attendance` button brings up a Discord Modal, where the user needs to answer a few questions before their attendance is confirmed. 

**TO-DO**: Add customization for certain specialized events (e.g. Chibachan drink preorders). Unfortunately, Modal `TextInput` field labels are limited to 45 characters, so the options cannot fit in the label. Maybe list them in the placeholder text?\
**TO-DO**: Allow a user to withdraw/modify their response.\
**TO-DO**: Allow organizers to delete responses via slash commands.