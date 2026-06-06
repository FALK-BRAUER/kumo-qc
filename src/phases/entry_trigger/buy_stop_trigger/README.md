# buy_stop_trigger

Scenario B intraday entry-trigger module for the #386 architecture proof.
It reads armed candidates and fires a market entry when the current 5-minute bar trades through a buy-stop level.
This folder contains only the trigger implementation and module-local notes.
Daily arming and broker submission belong to the arm phase and engine respectively.
