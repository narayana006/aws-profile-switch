# aws-profile-switch

Switch AWS profiles and SSO sessions quickly from the terminal, with fuzzy search and automatic login.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool.

**The problem it solves:** Switching between many AWS profiles means editing environment variables by hand and re-running SSO login when a session has expired.

## Who it is for

Engineers with more than a handful of AWS profiles.

## How it will work

1. You type a few letters of a profile name.
2. The tool picks the matching profile and checks whether its session is still valid.
3. It logs in if needed and sets the profile for your current shell.

## Planned features

Unticked items are not built yet.

- [ ] Fuzzy search over profiles in your AWS config
- [ ] Exports the profile into the current shell
- [ ] Runs SSO login only when the session has expired
- [ ] Shows the last-used profiles first
- [ ] Works in bash, zsh and fish

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
awsp prod-readonly
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
