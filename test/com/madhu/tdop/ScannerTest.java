
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

import static org.junit.Assert.*;

import org.junit.Test;

import com.madhu.tdop.Scanner;
import com.madhu.tdop.Terminal;

public class ScannerTest {
	@Test
	public void testID() {
		Scanner sc = new Scanner();
		// Order matters! First pattern that matches wins. 
        sc.addPattern("(", "\\(");
        sc.addPattern(")", "\\)");
        sc.addPattern("&&", "\\&\\&");
        sc.addPattern("||", "\\|\\|");
        sc.addPattern("!=", "\\!\\=");
        sc.addPattern("==", "\\=\\=");
        sc.addPattern("=", "\\=");
        sc.addPattern("+", "\\+");
        sc.addPattern("-", "\\-");
        sc.addPattern("*", "\\*");
        sc.addPattern("/", "\\/");
        sc.addPattern(",", "\\,");
        sc.addPattern("%", "\\%");
        sc.addPattern("INT", "[0-9]+");
        sc.addPattern("ID", "[a-zA-Z_][a-zA-Z_0-9]*");
        sc.addPattern("STRING", "'[^']*'");

        sc.addKeywords("ID", "UPDATE", "SELECT", "FROM", "SET", "WHERE", "OR", "AND");
        
        sc.setInput("bar foo UPDATE SELECT AND OR");
		Terminal t1 = sc.expect("ID");
		assertEquals("bar", t1.getValue());
		t1 = sc.expect("ID");
		assertEquals("foo", t1.getValue());
		String[] names = { "UPDATE", "SELECT", "AND", "OR" };
		for (String name : names) {
			t1 = sc.expect(name);
			assertEquals(name, t1.getValue());
		}
		assertTrue(sc.atEnd());
	}
}
