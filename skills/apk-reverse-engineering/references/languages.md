# English and Russian language handling

Documentation and built-in interface text are English. Accept Russian and English
requests with equal priority, including natural phrasing, inflections, typos and
mixed technical vocabulary. Do not require an English restatement. Ask questions,
explain blockers and write reports in the user's language unless they request
another language. Preserve all technical constraints regardless of language.

The quoted Russian inputs below are recognition examples, not untranslated
instructions. Their English meanings and controller mappings are normative:

| Example Russian input | English meaning / action |
| --- | --- |
| «проанализируй APK», «изучи приложение» | Analyze the APK; load this skill and follow the saved goal |
| «измени поведение», «пропатчь», «исправь» | Change behavior / patch / fix; follow baseline, build and verification rules |
| «на телефоне», «на подключенном устройстве» | Phone target; select the authorized physical serial |
| «в эмуляторе», «виртуальная среда», «виртуальный Android» | Managed emulator target |
| «без тестирования», «без запуска», «не проверять» | Explicit none target; runtime verdict remains untested |
| «авто», «автоматически», «сам» | Automatic working mode when referring to overall mode |
| «полуавто», «полуавтоматически», «с моей помощью» | Assisted working mode |
| «вручную», «ручной режим», «по шагам передавай мне» | Manual working mode |
| «готово», «я дошёл», «я дошел», «можешь продолжать», «теперь твоя очередь» | Actual ready/handoff signal in context; resume observation in place |
| «передай мне», «я сделаю сам», «теперь я» | Hand control to the user and wait |
| «попробуй сам» | Offer/permission to reproduce the discussed route; do not silently change the overall mode |
| «покажи скриншоты» | Publish relevant original screenshots |
| «останови анализ» | pause JOB |
| «продолжи анализ», «продолжи» | resume JOB and saved investigation; if a handoff is pending, interpret readiness from context |
| «останови веб-сервер» | server stop; preserve job data |
| «дай полную ссылку», «ссылку снова» | link JOB --format telegram; copy its entire URL including job and token |

Examples are not an exhaustive keyword parser. Resolve intent from the full
conversation; a quoted or hypothetical “ready” is not a live readiness signal.
Distinguish target from working mode. “Without testing” does not mean manual;
“virtual environment” does not imply automatic. A single navigation permission
does not replace the user's saved mode. Ask only when context leaves a material
choice unresolved, in the user's language.

Keep CLI commands, identifiers, hashes, paths, descriptors and URLs exact. Goals,
notes and evidence may contain Unicode; do not translate app literals or original
user evidence merely to match English documentation. ADB text input in this lab
still supports printable ASCII only: enter Russian text through the on-screen
keyboard or a separately supported, explicitly chosen input method. Do not
silently transliterate text when its exact value matters.
