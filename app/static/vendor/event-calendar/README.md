# Event Calendar — vendored

`@event-calendar/build` **5.12.0**, MIT licensed, zero runtime dependencies.
Copied from the npm tarball, not loaded from a CDN: this application self-hosts
its third-party assets so that no page hands a visitor's IP to someone else.

Used by the **admin** booking calendar only. The public and member calendars
stay server-rendered — they answer one question ("is this room free?"), which a
table answers in zero bytes and without JavaScript.

    js   130,062 raw / 42,394 gz
    css   15,537 raw /  3,217 gz

## Upgrading

    npm pack @event-calendar/build@<version>
    tar -xzf event-calendar-build-<version>.tgz
    cp package/dist/event-calendar.min.{js,css} app/static/vendor/event-calendar/

Then update the version here and re-run the calendar tests. Check the upstream
changelog first: https://github.com/vkurko/calendar/blob/master/CHANGELOG.md
