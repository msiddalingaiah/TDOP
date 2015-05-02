
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

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.regex.Matcher;

/**
 * A lightweight scanner (lexical analyzer) based on regular expressions.
 * The scanner maintains one terminal (token) lookahead.
 * 
 * This scanner ignores whitespace and attempts to find a regular expression
 * pattern that matches the input. If keywords are supplied, they are matched
 * against a defined list.
 * 
 * @author Madhu Siddalingaiah
 */
public class Scanner {
    private List<TerminalID> patterns;
    private HashMap<String, ArrayList<String>> keywords;
	private String input;
	private int column;
	private int line;
	private Terminal terminal;
	private Terminal lookAhead;

	public Scanner() {
        patterns = new ArrayList<>();
        keywords = new HashMap<>();
	}

	public void addPattern(String name, String regex) {
        patterns.add(new TerminalID(name, regex));
	}

	/**
	 * Add any number of possible keywords.
	 * This method can be called as many times as needed.
	 * 
	 * @param name - the name of a terminal that could be a keyword, e.g. "ID"
	 * @param keywordList - a line of possible keywords
	 */
	public void addKeywords(String name, String... keywordList) {
		if (!keywords.containsKey(name)) {
			keywords.put(name, new ArrayList<String>());
		}
		ArrayList<String> list = keywords.get(name);
		for (String keyword : keywordList) {
			list.add(keyword);
		}
	}

	public void setInput(String input) {
		for (TerminalID t : patterns) {
			t.init(input);
		}
		this.input = input;
		line = 1;
		lookAhead = next();
	}

	private Terminal next() {
		while (column < input.length() && Character.isWhitespace(input.charAt(column))) {
			if (input.charAt(column) == '\n') {
				line += 1;
			}
			column += 1;
		}
		if (column >= input.length()) {
			return null;
		}
		for (TerminalID tp : patterns) {
			Matcher m = tp.getMatcher();
			if (m.find(column) && m.start() == column) {
				int end = m.end();
				String name = tp.getName();
				String value = input.substring(column, end);
				ArrayList<String> list = keywords.get(name);
				Terminal t = new Terminal(name, value, line, column);
				if (list != null && list.contains(value)) {
					t = t.rename(value);
				}
				column = end;
				return t;
			}
		}
		throw new SyntaxError("Unexpected input: " + input.charAt(column), line, column);
	}

	public boolean matches(String... types) {
		if (lookAhead == null) {
			return false;
		}
		for (String type : types) {
			if (lookAhead.matches(type)) {
				terminal = lookAhead;
				lookAhead = next();
				return true;
			}
		}
		return false;
	}

	public Terminal expect(String... types) {
		if (matches(types)) {
			return terminal;
		}
		StringBuilder sb = new StringBuilder();
		for (String type : types) {
			sb.append(' ');
			sb.append(type);
		}
		String ts = sb.toString();
		if (lookAhead == null) {
			throw new SyntaxError("Expected" + ts + ", found end of input", line, column);
		}
		throw new SyntaxError("Expected" + ts + ", found " + lookAhead, line, column);
	}

	public boolean atEnd() {
		return lookAhead == null;
	}

	public Terminal getTerminal() {
		return terminal;
	}
}
