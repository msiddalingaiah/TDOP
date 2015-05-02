# TDOP

A simple, easy to use, LL(1) top down operator precedence parser.

This is an LL(1) recursive descent parser incorporating ideas described by Vaughan Pratt in his 1973 paper "Top down operator precedence".
This technique doesn't require any extra tools or lots of coding. Arbitrary levels of operator precedence can be added easily.
While there are many parsing techniques available, this one is best suited for little languages that are required from time to time.

More information is available [here](http://en.wikipedia.org/wiki/Pratt_parser)

The source code compiles and runs with Java 7 and JUnit 4.
An Eclipse project is available.

If you have [GraphViz](http://www.graphviz.org) installed, you can generate a view an Abstract Syntax Tree with this command:

java -cp bin com.madhu.tdop.SQLParser  | dot -Tpng > x.png

The output is a .png image.

Madhu Siddalingaiah
