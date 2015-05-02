
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
import java.util.Iterator;

/**
 * A generic Tree that can represent a node in an Abstract Syntax Tree.
 * 
 * @author Madhu Siddalingaiah
 *
 * @param <V> - the value class this tree can contain.
 */
public class Tree<V> implements Iterable<Tree<V>> {
	private V value;
	private ArrayList<Tree<V>> children;
	private int id;
	
	public Tree(V value) {
		this.value = value;
		this.children = new ArrayList<Tree<V>>();
	}
	
	public Tree<V> add(Tree<V> child) {
		children.add(child);
		return this;
	}
	
	public Tree<V> add(V value) {
		children.add(new Tree<V>(value));
		return this;
	}
	
	public Tree<V> get(int i) {
		return children.get(i);
	}

	public V getValue() {
		return value;
	}
	
	public int size() {
		return children.size();
	}

	public boolean isLeaf() {
		return children.size() == 0;
	}

	/**
	 * Produces an S-expression represented by this tree.
	 * 
	 * @see java.lang.Object#toString()
	 */
	@Override
	public String toString() {
		StringBuilder sb = new StringBuilder();
		doToString(sb, this);
		return sb.toString();
	}

	private void doToString(StringBuilder sb, Tree<V> tree) {
		if (tree.isLeaf()) {
			sb.append(tree.getValue());
		} else {
			sb.append('(');
			sb.append(tree.getValue());
			int size = tree.size();
			for (int i = 0; i < size; i++) {
				sb.append(' ');
				doToString(sb, tree.get(i));
			}
			sb.append(')');
		}
	}

	/**
	 * Produces dot file format suitable for use with GraphViz.
	 * 
	 * @link http://www.graphviz.org
	 * @return - A String in dot file format.
	 */
    public String toDot() {
    	label(1);
        return String.format("digraph ast {%s\n}", doToDot(""));
    }

    public int label(int id) {
        this.id = id;
        id += 1;
        for (Tree<V> c : children) {
            id = c.label(id);
        }
        return id;
    }

    public String doToDot(String dot) {
        dot = String.format("%s\n%d [label=\"%s\"];", dot, id, value);
        for (Tree<V> c : children) {
            dot = c.doToDot(dot);
            dot = String.format("%s\n%d -> %d;", dot, id, c.id);
        }
        return dot;
    }

	public static void main(String[] args) {
		Tree<String> t = new Tree<String>("root");
		t.add("a").add("b").add(new Tree<String>("r2").add("c").add("d"));
//		System.out.println(t);
		System.out.println(t.toDot());
	}

	@Override
	public Iterator<Tree<V>> iterator() {
		return children.iterator();
	}
}
