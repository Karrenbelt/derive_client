#!/usr/bin/env bash

set -e

SLEEP_TIME=3

cowsay The Derive client offers both a library and a cli tool to manage positions on Derive.

sleep $SLEEP_TIME

clear

cowsay "The client can be installed from pip as so;" 

echo "pip install derive-client"

sleep $SLEEP_TIME

clear

cowsay "Once the Derive client is installed, we can programatically interact with Derive"

drv

sleep $SLEEP_TIME
clear

cowsay we can fetch markets by instrument type and currency

drv instruments fetch --help

sleep $SLEEP_TIME
clear

echo \`drv instruments fetch -i perp\`
drv instruments fetch -i perp

sleep $SLEEP_TIME
clear

echo \`drv instruments fetch -i perp -c btc\`
drv instruments fetch -i perp -c btc
sleep $SLEEP_TIME
clear


cowsay we can manage orders
echo \`drv orders\`
drv orders
sleep $SLEEP_TIME
clear

cowsay we can create orders
echo \`drv orders create -s sell -i ETH-PERP -a 1 -p 3000\`
drv orders create -s sell -i ETH-PERP -a 1 -p 3000
sleep $SLEEP_TIME
clear

cowsay "we can then retrieve them"
echo \`drv orders fetch -i ETH-PERP --status open\`
drv orders fetch -i ETH-PERP --status open
sleep $SLEEP_TIME
clear


cowsay "we can then cancel them"
echo \`drv orders cancel_all\`
drv orders cancel_all
sleep $SLEEP_TIME
clear

cowsay "we can also check our balances"
echo \`drv collateral fetch\`
drv collateral fetch
sleep $SLEEP_TIME
clear

cowsay "we can also check our positions"
echo \`drv positions fetch\`
drv positions fetch
sleep $SLEEP_TIME
clear

