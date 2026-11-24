# Changelog

## [0.4.0](https://github.com/KLTsai/next-is-you/compare/v0.3.0...v0.4.0) (2026-11-24)


### Features

* allow only one running visit at a time ([#174](https://github.com/KLTsai/next-is-you/issues/174)) ([e97c757](https://github.com/KLTsai/next-is-you/commit/e97c757dd1ff88e9d9c41e515866ca6e34c36b0e))
* show paused reminders during send interruption ([#157](https://github.com/KLTsai/next-is-you/issues/157)) ([53553b9](https://github.com/KLTsai/next-is-you/commit/53553b987ecfe745868399b79c8db8d80a50ec39))


### Bug Fixes

* keep an invitee on the consent page until they join ([#161](https://github.com/KLTsai/next-is-you/issues/161)) ([a710d3e](https://github.com/KLTsai/next-is-you/commit/a710d3e2d07de9231acd245decfbf16459b37084))
* keep an open calendar and typed fields through background updates ([#190](https://github.com/KLTsai/next-is-you/issues/190)) ([#191](https://github.com/KLTsai/next-is-you/issues/191)) ([811375c](https://github.com/KLTsai/next-is-you/commit/811375c08e35bcfc5d3ce4a508346a637d35e489))
* keep the member label the organizer is typing ([#178](https://github.com/KLTsai/next-is-you/issues/178)) ([af084d2](https://github.com/KLTsai/next-is-you/commit/af084d212657b67d9904693635e2797646a70553))
* keep the page still and the typed field focused on repaint ([#185](https://github.com/KLTsai/next-is-you/issues/185)) ([#186](https://github.com/KLTsai/next-is-you/issues/186)) ([328d4d8](https://github.com/KLTsai/next-is-you/commit/328d4d87947285a449e624c92c748b0d1c4d9111))
* keep the page still when the date field has focus on repaint ([#182](https://github.com/KLTsai/next-is-you/issues/182)) ([#193](https://github.com/KLTsai/next-is-you/issues/193)) ([df18840](https://github.com/KLTsai/next-is-you/commit/df18840ef062da50f3474a6db4b9a1de5fcd952a))
* let the organizer pick the word while typing with an input method ([#195](https://github.com/KLTsai/next-is-you/issues/195)) ([#196](https://github.com/KLTsai/next-is-you/issues/196)) ([787d6a0](https://github.com/KLTsai/next-is-you/commit/787d6a0af5ba56888bdd3f14a1bd19c9d0c02493))
* match visit-day clinics before starting reminders ([#158](https://github.com/KLTsai/next-is-you/issues/158)) ([d233d40](https://github.com/KLTsai/next-is-you/commit/d233d400a9ac5f2b86eb9cd05c25938ba867e416))
* stop the registration number field from scrolling the page on repaint ([#185](https://github.com/KLTsai/next-is-you/issues/185)) ([#187](https://github.com/KLTsai/next-is-you/issues/187)) ([55de741](https://github.com/KLTsai/next-is-you/commit/55de741e4172e2b913053223cefa59a5a0eb5771))

## [0.3.0](https://github.com/KLTsai/next-is-you/compare/v0.2.3...v0.3.0) (2026-11-19)


### Features

* check saved drafts as soon as the hospital publishes their day ([4061cf5](https://github.com/KLTsai/next-is-you/commit/4061cf5b84b2f41ad1ab97649e19ccdd3892882a))
* explain a refused Start for a not-yet-published clinic schedule day ([63b19bc](https://github.com/KLTsai/next-is-you/commit/63b19bc5dd6e503c8c705a09f5efe14ee53f2ae2))
* make reminder setup independent of any one hospital ([42e709f](https://github.com/KLTsai/next-is-you/commit/42e709f0e9cf03424347b0a2b34595e07a572d8a))
* show a not-yet-published clinic schedule day in the setup form ([a41c269](https://github.com/KLTsai/next-is-you/commit/a41c269462e0d1f98836a216f3246035add7f931))
* show each clinic with the hospital's own label and published details ([7fcd836](https://github.com/KLTsai/next-is-you/commit/7fcd836fe7181fd89c72593975c98412a7009817))
* start a hospital that publishes only the current number on the visit day ([3f05848](https://github.com/KLTsai/next-is-you/commit/3f05848e8fb46db86fc1460d4717039307cd81e4))
* stop enumerating hospitals in the visits table ([7a1b103](https://github.com/KLTsai/next-is-you/commit/7a1b1037b6b5455c43792318cb3aabef77271453))
* word the current-number-only setup and refused Start for the organizer ([c62358a](https://github.com/KLTsai/next-is-you/commit/c62358ac0d633429a00121da0be5cd56c9232218))


### Bug Fixes

* announce the whole joined message to screen readers ([14e6dd6](https://github.com/KLTsai/next-is-you/commit/14e6dd675e31037a69d2d48c222cd33042d5c45e)), closes [#118](https://github.com/KLTsai/next-is-you/issues/118)
* do not memoise failed NTUH schedule reads and share the unpublished window rule ([81bf901](https://github.com/KLTsai/next-is-you/commit/81bf9019ade070ccc7b8af4bb44b07233c368baa))
* give a refused Start for an unpublished day a plain fallback text ([7ac7b79](https://github.com/KLTsai/next-is-you/commit/7ac7b79b20782350d8757e63c101b9a94606d681))
* keep a draft unchanged when Start is refused for an unpublished day ([c9ded31](https://github.com/KLTsai/next-is-you/commit/c9ded31aa9d5eabcee8cfb7e591937ae65ced3ea))
* keep cleaning up expired data while sends are held ([34b52e0](https://github.com/KLTsai/next-is-you/commit/34b52e0a9aa4ebda20ff673da38df1cd6c7bb346))
* keep cleaning up expired data while sends are held ([600d595](https://github.com/KLTsai/next-is-you/commit/600d5950074e94f915503b408eac8dc8cd8bffd4)), closes [#117](https://github.com/KLTsai/next-is-you/issues/117)
* let a reader answer not applicable and derive full schedule from both methods ([fd17e7d](https://github.com/KLTsai/next-is-you/commit/fd17e7d248b59e82cf85bfa9e63555d8e09d5953))
* match the sign-in failure page to the app and cover the joined state in the rehearsal ([813e089](https://github.com/KLTsai/next-is-you/commit/813e0890902c0f9a348a4ed1b24ef3457d4e76d4)), closes [#118](https://github.com/KLTsai/next-is-you/issues/118)
* refuse unsupported hospital drafts ([#132](https://github.com/KLTsai/next-is-you/issues/132)) ([6e27787](https://github.com/KLTsai/next-is-you/commit/6e27787ec6c906c4f12772862db2ed6f96052309))
* show a plain Chinese page when LINE sign-in or an invitation fails ([a3eeadf](https://github.com/KLTsai/next-is-you/commit/a3eeadf9ddd8074ebea476b9296c84944e7cb510))
* show a plain Chinese page when LINE sign-in or an invitation fails ([0d3590f](https://github.com/KLTsai/next-is-you/commit/0d3590fa5955a33e5c64413b617dc4f5f5589438)), closes [#118](https://github.com/KLTsai/next-is-you/issues/118)

## [0.2.3](https://github.com/KLTsai/next-is-you/compare/v0.2.2...v0.2.3) (2026-11-16)


### Bug Fixes

* rollback testing ([71ff166](https://github.com/KLTsai/next-is-you/commit/71ff166e5d10cb32a35ff979798ba0cc25daeed1))
* rollback testing ([e5f656c](https://github.com/KLTsai/next-is-you/commit/e5f656c5bf2ef619e024d8c3b205d4855f3aaf30))

## [0.2.2](https://github.com/KLTsai/next-is-you/compare/v0.2.1...v0.2.2) (2026-11-16)


### Bug Fixes

* remove blank line ([6ebc93d](https://github.com/KLTsai/next-is-you/commit/6ebc93d62ae24430054ae877315cbe74ab4065e4))
* remove blank line ([4585be2](https://github.com/KLTsai/next-is-you/commit/4585be243772b1e43801004c789cebd6702c6758))

## [0.2.1](https://github.com/KLTsai/next-is-you/compare/v0.2.0...v0.2.1) (2026-11-14)


### Documentation

* **ci-cd:** correct the bump rule for docs commits ([5c7c02f](https://github.com/KLTsai/next-is-you/commit/5c7c02f026c79a5e0a1d7d93f224e217f12bf644))
* **ci-cd:** record why a merged release PR must be promoted ([1a7e76e](https://github.com/KLTsai/next-is-you/commit/1a7e76e084790c211db39433706e6ae20b00475e))

## [0.2.0](https://github.com/KLTsai/next-is-you/compare/v0.1.0...v0.2.0) (2026-10-31)


### Features

* **ci-cd:** add release-please versioning and tagged production deploy ([5e433e4](https://github.com/KLTsai/next-is-you/commit/5e433e49189d18ea9333f813062bffc24835e7ff))
* **ci-cd:** add release-please versioning and tagged production deploy ([8652200](https://github.com/KLTsai/next-is-you/commit/865220056ab6deb9e714682e0106824f06c32239))
* **frontend:** catalog-driven cascading reminder-setup UI ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#54](https://github.com/KLTsai/next-is-you/issues/54)) ([73260e2](https://github.com/KLTsai/next-is-you/commit/73260e2ba1aedc7a11820c0c2114b01cf6fc968e))
* **next_is_you:** serve a hospital catalog and clinic roster for the setup picker ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#49](https://github.com/KLTsai/next-is-you/issues/49)) ([bec72a5](https://github.com/KLTsai/next-is-you/commit/bec72a5a6900983b782e70f5b947f686f8b25288))


### Bug Fixes

* **ci-cd:** baseline release-please at the current held production commit ([ba145d7](https://github.com/KLTsai/next-is-you/commit/ba145d72a5be91e6eed56e08bb587f2940299995))
* **ci-cd:** baseline release-please at the current held production commit ([f23ebf4](https://github.com/KLTsai/next-is-you/commit/f23ebf4b67d0c567c68aab61b098cf00766bca46))
* **ci-cd:** match production deploy to the prod GitHub Environment ([ab66637](https://github.com/KLTsai/next-is-you/commit/ab6663786bf3f081c33e72b2a2bd162ae6f0d801))
* **ci-cd:** match production deploy to the prod GitHub Environment ([f4bf056](https://github.com/KLTsai/next-is-you/commit/f4bf056b2ea749989f493b2d1ecfe32220d56807))
