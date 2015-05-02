
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

import com.madhu.tdop.SQLParser;
import com.madhu.tdop.Terminal;
import com.madhu.tdop.Tree;

public class ParserTest {
	@Test
	public void testUpdate() {
		SQLParser p = new SQLParser();
		Tree<Terminal> tree = p.parse("update foo set bar = bar + 2*baz-2/3%6, a=1 where bar == '' or baz == 'Y'");
		assertEquals("(UPDATE (SET (= BAR (- (+ BAR (* 2 BAZ)) (% (/ 2 3) 6))) (= A 1)) (OR (== BAR '') (== BAZ 'Y')))", tree.toString());
	}

	@Test
	public void testSelect() {
		SQLParser p = new SQLParser();
		Tree<Terminal> tree = p.parse("select 1+2*i, 2/a from foo where bar == '' or baz == 'Y'");
		assertEquals("(SELECT (list (+ 1 (* 2 I)) (/ 2 A)) FOO (OR (== BAR '') (== BAZ 'Y')))", tree.toString());
	}
}
