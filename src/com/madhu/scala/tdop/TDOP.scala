
package com.madhu.scala.tdop

import java.util.regex.Pattern
import java.util.regex.Matcher
import scala.collection.mutable.ArrayBuffer
import scala.collection.mutable.Stack

sealed class TerminalID(val name: String, val regex: String) {
  val pattern: Pattern = Pattern.compile(regex)
  var matcher: Matcher = null

  def init(input: String) = matcher = pattern.matcher(input)
  override def toString(): String = name
}

class Terminal(val name: String, value: String) {
  override def toString(): String = String.format("%s", value)
  def matches(that: TerminalID) = this.name.equals(that.name)
  def matches(that: String) = this.name.equals(that)
}

class SyntaxError(val message: String) extends RuntimeException(message) {
}

class Scanner(
    val input: String,
    val patterns: List[TerminalID],
    var lookAhead: Option[Terminal] = None,
    var terminal: Terminal = null,
    var column: Int = 0) {
  def this(input: String) = {
    this(input, List(
      new TerminalID("(", "\\("),
      new TerminalID(")", "\\)"),
      new TerminalID("&&", "\\&\\&"),
      new TerminalID("||", "\\|\\|"),
      new TerminalID("!=", "\\!\\="),
      new TerminalID("==", "\\=\\="),
      new TerminalID("+", "\\+"),
      new TerminalID("-", "\\-"),
      new TerminalID("*", "\\*"),
      new TerminalID("/", "\\/"),
      new TerminalID("INT", "[0-9]+")
    ))
    patterns.foreach(p => p.init(input))
    lookAhead = next
  }

  def next(): Option[Terminal] = {
    while (column < input.length() && input.charAt(column).isWhitespace) {
      column += 1
    }
    if (column >= input.length()) {
      return None
    }
    patterns.foreach(p => {
      val m = p.matcher
      if (m.find(column) && m.start() == column) {
        val end = m.end()
        val t = new Terminal(p.name, input.substring(column, end))
        column = end
        return Some(t)
      }
    })
    throw new SyntaxError("Unrecognized input: " + input.charAt(column))
  }

  def matches(types: String*): Boolean = {
    if (lookAhead == None) {
      return false
    }
    types.foreach(t => {
      lookAhead match {
        case Some(l) => {
          if (l.matches(t)) {
            terminal = l
            lookAhead = next
            return true
          }
        }
        case None =>
      }
    })
    false
  }

  def expect(types: String*): Terminal = {
    if (matches(types:_*)) {
      return terminal
    }
    throw new SyntaxError("Expected one of " + types.mkString(" ") + ", found " + lookAhead.getOrElse("?null"))
  }

  def atEnd(): Boolean = {
      lookAhead match {
        case Some(l) => false
        case None => true
      }
  }
}

class Tree[V](val value: V, val children: ArrayBuffer[Tree[V]] = new ArrayBuffer[Tree[V]]()) {
  def iterator = children.iterator

  def apply(index: Int): Tree[V] = {
    children(index)
  }

  def +=(that: Tree[V]): Tree[V] = {
    children += that
    this
  }

  def +=(that: V): Tree[V] = {
    children += new Tree(that)
    this
  }

  def size(): Int = children.size

  def isLeaf(): Boolean = size == 0

  override def toString(): String = {
    val sb: StringBuilder = new StringBuilder()
    doToString(sb)
    sb.toString
  }

  def doToString(sb: StringBuilder) {
    if (isLeaf) {
      sb ++= value.toString
    } else {
      sb += '('
      sb ++= value.toString
      children.foreach(c => {
        sb += ' '
        c.doToString(sb)
      })
      sb += ')'
    }
  }
}

class Parser(val sc: Scanner,
    var prec: Array[Array[String]] = null,
    var stack: Stack[Tree[Terminal]] = new Stack()) {
  def this(input: String) = {
    this(new Scanner(input))
    prec = Array(Array("&&", "||"), Array("==", "!="), Array("+", "-"), Array("*", "/"))
  }

  def parse(): Tree[Terminal] = {
    val tree = parseExp
    if (!sc.atEnd) {
      throw new SyntaxError("Unexpected input " + sc.terminal)
    }
    tree
  }

  def parseExp(): Tree[Terminal] = {
    parseX(0)
  }

  def parseX(index: Int): Tree[Terminal] = {
    var result = parseY(index)
    while (sc.matches(prec(index) : _*)) {
      val temp = new Tree(sc.terminal)
      temp += result
      temp += parseY(index)
      result = temp
    }
    result
  }

  def parseY(index: Int): Tree[Terminal] = {
    if (index >= prec.length-1) return parsePrim
    parseX(index + 1)
  }

  def parsePrim(): Tree[Terminal] = {
    if (sc.matches("(")) {
      val tree = parseExp
      sc.expect(")")
      return tree
    }
    if (sc.matches("-")) {
      val tree = new Tree(sc.terminal)
      tree += parsePrim
      return tree
    }
    new Tree(sc.expect("INT"))
  }
}

object ParserTest {
  def main(args: Array[String]): Unit = {
    val p = new Parser("1+2* 4 == 5/6 && 7 != 8")
    println(p.parse)
  }
}
