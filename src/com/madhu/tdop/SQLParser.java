
/*
 * Copyright 2015 Madhu Siddalingaiah
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package com.madhu.tdop;

/**
 * A trivial SQL subset parser for illustration purposes.
 * This could be expanded as needed.
 * 
 * This is an LL(1) recursive descent parser incorporating Top Down Operator Precedence ideas
 * described by Vaughan Pratt in his 1973 paper "Top down operator precedence".
 * 
 * More information is available here:
 * 
 * @link http://en.wikipedia.org/wiki/Pratt_parser
 * 
 * @author Madhu Siddalingaiah
 */
public class SQLParser {
	/**
	 * List of operators in order of precedence from lowest to highest
	 */
    private String[][] prec = { { "AND", "OR" }, { "==", "!=" }, { "+", "-" }, { "*", "/", "%" } };
	private Scanner scanner;

	public SQLParser() {
		scanner = new Scanner();
		// Order matters! First pattern that matches wins. 
        scanner.addPattern("(", "\\(");
        scanner.addPattern(")", "\\)");
        scanner.addPattern("&&", "\\&\\&");
        scanner.addPattern("||", "\\|\\|");
        scanner.addPattern("!=", "\\!\\=");
        scanner.addPattern("==", "\\=\\=");
        scanner.addPattern("=", "\\=");
        scanner.addPattern("+", "\\+");
        scanner.addPattern("-", "\\-");
        scanner.addPattern("*", "\\*");
        scanner.addPattern("/", "\\/");
        scanner.addPattern(",", "\\,");
        scanner.addPattern("%", "\\%");
        scanner.addPattern("INT", "[0-9]+");
        scanner.addPattern("ID", "[a-zA-Z_][a-zA-Z_0-9]*");
        scanner.addPattern("STRING", "'[^']*'");

        scanner.addKeywords("ID", "UPDATE", "SELECT", "FROM", "SET", "WHERE", "OR", "AND");
	}
	
	public Tree<Terminal> parse(String line) {
		scanner.setInput(line.toUpperCase());
		Tree<Terminal> tree = null;
		if (scanner.matches("SELECT")) {
			tree = parseSelect(scanner.getTerminal());
		} else if (scanner.matches("UPDATE")) {
			tree = parseUpdate(scanner.getTerminal());
		} else {
			throw new SyntaxError("What?", 0, 0);
		}
		if (!scanner.atEnd()) {
			Terminal t = scanner.getTerminal();
			throw new SyntaxError("Unexpected input: " + t.getValue(), t.getLine(), t.getColumn());
		}
		return tree;
	}

	// select -> 'select' exp (, exp)* from ID where exp
	private Tree<Terminal> parseSelect(Terminal select) {
		Tree<Terminal> result = new Tree<Terminal>(select);
		// create a synthetic node for the list of expressions 
		Tree<Terminal> list = new Tree<Terminal>(select.rename("list", "list"));
		do {
			list.add(parseExp());
		} while (scanner.matches(","));
		result.add(list);
		scanner.expect("FROM");
		result.add(scanner.expect("ID"));
		scanner.expect("WHERE");
		result.add(parseExp());
		return result;
	}

	// update -> 'update' ID 'set' assign (, assign)* where exp
	private Tree<Terminal> parseUpdate(Terminal update) {
		Tree<Terminal> result = new Tree<Terminal>(update);
		scanner.expect("ID"); // ignore table name
		Tree<Terminal> set = new Tree<Terminal>(scanner.expect("SET"));
		do {
			set.add(parseAssign());
		} while (scanner.matches(","));
		result.add(set);
		scanner.expect("WHERE");
		result.add(parseExp());
		return result;
	}

	// assign -> ID '=' STRING
	private Tree<Terminal> parseAssign() {
		Terminal id = scanner.expect("ID");
		Tree<Terminal> result = new Tree<Terminal>(scanner.expect("="));
		result.add(id);
		result.add(parseExp());
		return result;
	}

    public Tree<Terminal> parseExp() {
        return parseX(0);
    }

    public Tree<Terminal> parseX (int index) {
        Tree<Terminal> result = parseY(index);
        while (scanner.matches(prec[index])) {
            Tree<Terminal> temp = new Tree<>(scanner.getTerminal());
            temp.add(result);
            temp.add(parseY(index));
            result = temp;
        }
        return result;
    }

    public Tree<Terminal> parseY (int index) {
        if (index >= prec.length - 1) {
            return parsePrim();
        }
        return parseX(index + 1);
    }
	
	private Tree<Terminal> parsePrim() {
		Terminal t = scanner.expect("ID", "STRING", "(", "INT");
		if (t.matches("(")) {
			Tree<Terminal> tree = parseExp();
			scanner.expect(")");
			return tree;
		}
		return new Tree<Terminal>(t);
	}

	// java -cp bin com.madhu.tdop.SQLParser  | dot -Tpng > x.png
	public static void main(String[] args) {
		SQLParser p = new SQLParser();
//		Tree<Terminal> tree = p.parse("update foo set bar = bar + 2*baz-2/3%6 where bar == '' or baz == 'Y'");
		Tree<Terminal> tree = p.parse("select 1+2*i, 2/a from foo where bar == '' or baz == 'Y'");
//		System.out.println(tree);
		System.out.println(tree.toDot());
	}
}
