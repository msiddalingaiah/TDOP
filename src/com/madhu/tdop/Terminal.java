
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
 * A terminal (token) representing a set of characters in the input or other symbol.
 * Usually, a Scanner instance will return a valid terminal, but it is possible to
 * create convenience terminals for use within the output syntax tree.
 * 
 * @author Madhu Siddalingaiah
 */
public class Terminal {
    private String name;
    private String value;
    private int line;
    private int column;

    public Terminal(String name, String value, int line, int column) {
        this.name = name;
        this.value = value;
        this.line = line;
        this.column = column;
    }

    public boolean matches(TerminalID t) {
        return name.equals(t.getName());
    }

    public boolean matches(String name) {
        return this.name.equals(name);
    }

    public String getValue() {
    	return value;
    }

    public void setValue(String value) {
    	this.value = value;
    }

    public String getName() {
		return name;
	}

	public int getLine() {
		return line;
	}

	public int getColumn() {
		return column;
	}

	@Override
    public String toString () {
        return value;
    }

	/**
	 * Creates a new terminal with the given name.
	 * 
	 * @param newName - the name for the new terminal
	 * @return - a copy of this terminal a new name
	 */
	public Terminal rename(String newName) {
		return new Terminal(newName, value, line, column);
	}

	/**
	 * Creates a new terminal with the given name and value.
	 * 
	 * @param newName - the name for the new terminal
	 * @param newValue - value for the new terminal
	 * @return - a copy of this terminal a new name and value
	 */
	public Terminal rename(String newName, String newValue) {
		return new Terminal(newName, newValue, line, column);
	}
}
