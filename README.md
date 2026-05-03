### HRF Boardgames App

#### One-Time Setup

**1.** In **scala-js-dom-reduced** dir (only needed once, or after changes to this library):
```
sbt publishLocal
```

**2.** In **good-game** dir (only needed once to create the database):
```
sbt "run create ../good-game-database ../haunt-roll-fail http://localhost:7070 http://localhost:7070/hrf/ 7070"
```

---

#### Every Session (two terminals)

**Terminal 1** — In **haunt-roll-fail** dir (auto-recompiles on every file save):
```
sbt fastOptJS
```

**Terminal 2** — In **good-game** dir (starts the server):
```
sbt "run run ../good-game-database ../haunt-roll-fail http://localhost:7070 http://localhost:7070/hrf/ 7070"
```

Then open `http://localhost:7070/hrf/` in your browser. After editing any `.scala` file, wait for Terminal 1 to finish compiling, then refresh the browser.
